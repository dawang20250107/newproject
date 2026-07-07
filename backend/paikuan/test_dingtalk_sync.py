"""钉钉审批同步：通用字段映射、任务分类、同步/刷新落库、查询分类（client 全 mock）。"""
import json
from decimal import Decimal
from unittest import mock

from django.test import Client, TestCase

from paikuan import dingtalk_sync as sync
from paikuan.models import ApprovalRecord, PaikuanUser
from paikuan.views import make_token

# 报销单形态（对照上传的 PDF）
DETAIL_REIMB = {
    '_instance_id': 'INST-1', 'business_id': '202603171454000116103',
    'title': '郭勇提交的差旅费报销单', 'originator_userid': 'U-guoyong',
    'originator_dept_name': '劳务事业部-项目四部', 'status': 'COMPLETED', 'result': 'agree',
    'form_component_values': [
        {'name': '申请人', 'value': '郭勇'},
        {'name': '部门', 'value': '劳务事业部'},
        {'name': '报销金额(元)', 'value': '600.00', 'component_type': 'MoneyField'},
        {'name': '总报销金额(元)', 'value': '600.00', 'component_type': 'MoneyField'},
        {'name': '收款账号', 'value': '郭勇（钉钉账号）'},
    ],
    'tasks': [{'userid': 'U-approver', 'task_status': 'RUNNING'}],
}
# 付款审批形态（收款方=供应商、金额带千分位、审批中）
DETAIL_PAY = {
    '_instance_id': 'INST-2', 'business_id': 'DTPAY0001', 'title': '供应商货款付款审批',
    'originator_userid': 'U-li', 'originator_dept_name': '运输事业部', 'status': 'RUNNING', 'result': '',
    'form_component_values': [
        {'name': '申请金额', 'value': '286,400.00', 'component_type': 'MoneyField'},
        {'name': '收款单位', 'value': '云南顺通物流'},
        {'name': '申请人', 'value': '李文强'},
    ],
    'tasks': [{'userid': 'U-me', 'task_status': 'RUNNING'}],
}


class MappingTests(TestCase):
    def test_reimbursement_mapping(self):
        f = sync.instance_to_fields(DETAIL_REIMB)
        self.assertEqual(f['applicant'], '郭勇')
        self.assertEqual(f['department'], '劳务事业部')
        self.assertEqual(f['approval_number'], '202603171454000116103')
        self.assertEqual(len(f['approval_number']), 21)
        self.assertEqual(f['amount'], Decimal('600.00'))
        self.assertEqual(f['payee'], '郭勇（钉钉账号）')     # 收款账号=本人
        self.assertEqual(f['status'], 'approved')
        self.assertEqual(f['dingtalk_instance_id'], 'INST-1')
        self.assertEqual(f['ext_source'], 'dingtalk')
        self.assertTrue(f['ext_raw']['form'])               # 全表单留存

    def test_payment_mapping_thousands_and_supplier(self):
        f = sync.instance_to_fields(DETAIL_PAY)
        self.assertEqual(f['amount'], Decimal('286400.00'))  # 千分位正确解析
        self.assertEqual(f['payee'], '云南顺通物流')          # 收款单位=供应商
        self.assertEqual(f['department'], '运输事业部')
        self.assertEqual(f['status'], 'pending')

    def test_amount_prefers_total_field(self):
        d = {'form_component_values': [
            {'name': '明细金额', 'value': '100', 'component_type': 'MoneyField'},
            {'name': '总金额', 'value': '350', 'component_type': 'MoneyField'},
            {'name': '明细金额', 'value': '250', 'component_type': 'MoneyField'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('350'))

    def test_status_mapping_all_cases(self):
        self.assertEqual(sync.map_status('COMPLETED', 'agree'), 'approved')
        self.assertEqual(sync.map_status('COMPLETED', 'refuse'), 'rejected')
        self.assertEqual(sync.map_status('RUNNING', ''), 'pending')
        self.assertEqual(sync.map_status('NEW', ''), 'pending')
        self.assertEqual(sync.map_status('TERMINATED', ''), 'canceled')
        self.assertEqual(sync.map_status('CANCELED', ''), 'canceled')

    def test_department_match_and_fallback(self):
        self.assertEqual(sync.match_department('运输事业部-西南大区'), '运输事业部')
        self.assertEqual(sync.match_department('不在枚举里的部门'), '')
        # 兜底集团总部
        self.assertEqual(sync.instance_to_fields(
            {'_instance_id': 'x', 'title': 't', 'form_component_values': []})['department'], '集团总部')

    def test_classify(self):
        self.assertEqual(sync.classify(DETAIL_PAY, 'U-me'), 'todo')       # 有 RUNNING 任务
        done = {'tasks': [{'userid': 'U-me', 'task_status': 'COMPLETED'}]}
        self.assertEqual(sync.classify(done, 'U-me'), 'done')
        orig = {'originator_userid': 'U-me', 'tasks': []}
        self.assertEqual(sync.classify(orig, 'U-me'), 'originated')


class SyncEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        admin = PaikuanUser(phone='13900008800', name='DTAdmin', role='super_admin',
                            job_title='finance_director', departments=['运输事业部'],
                            is_active=True, is_approved=True)
        admin.set_password('Test123456'); admin.save()
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {make_token(admin)}'}

    def _post(self, path, body):
        return self.client.post(path, data=json.dumps(body),
                                content_type='application/json', **self.auth)

    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_sync_creates_then_updates_by_instance_id(self, m_get):
        m_get.side_effect = lambda iid: DETAIL_PAY if iid == 'INST-2' else DETAIL_REIMB
        # 首次：新建两条
        r = self._post('/api/pk/dingtalk/sync', {'instance_ids': ['INST-1', 'INST-2']})
        d = r.json()['data']
        self.assertEqual(d['created'], 2)
        self.assertEqual(d['updated'], 0)
        rec = ApprovalRecord.objects.get(dingtalk_instance_id='INST-1')
        self.assertEqual(rec.status, 'approved')
        self.assertEqual(rec.payee, '郭勇（钉钉账号）')
        # 再次同步同一实例：更新而非重复
        r2 = self._post('/api/pk/dingtalk/sync', {'instance_ids': ['INST-1']})
        self.assertEqual(r2.json()['data']['updated'], 1)
        self.assertEqual(ApprovalRecord.objects.filter(dingtalk_instance_id='INST-1').count(), 1)

    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_refresh_writes_back_status_change(self, m_get):
        # 先建一条 pending 的同步记录
        m_get.return_value = DETAIL_PAY
        self._post('/api/pk/dingtalk/sync', {'instance_ids': ['INST-2']})
        rec = ApprovalRecord.objects.get(dingtalk_instance_id='INST-2')
        self.assertEqual(rec.status, 'pending')
        # 钉钉侧变为已通过 → 刷新回写
        approved = {**DETAIL_PAY, 'status': 'COMPLETED', 'result': 'agree'}
        m_get.return_value = approved
        r = self._post('/api/pk/dingtalk/refresh', {'instance_ids': ['INST-2']})
        self.assertEqual(r.json()['data']['updated'], 1)
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'approved')

    @mock.patch('paikuan.dingtalk_client.list_process_codes')
    @mock.patch('paikuan.dingtalk_client.list_instance_ids')
    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_query_filters_by_task_and_marks_synced(self, m_get, m_list, m_codes):
        m_codes.return_value = [{'process_code': 'PC1', 'name': '付款审批'}]
        m_list.return_value = ['INST-2']
        m_get.return_value = DETAIL_PAY
        # 预置一条已同步
        ApprovalRecord.objects.create(
            applicant='李文强', department='运输事业部', approval_number='DTPAY0001',
            summary='供应商货款', amount=Decimal('286400'), payee='云南顺通物流',
            status='pending', dingtalk_instance_id='INST-2')
        r = self._post('/api/pk/dingtalk/query',
                       {'userid': 'U-me', 'start': '2026-06-01', 'end': '2026-06-30', 'status': 'todo'})
        d = r.json()['data']
        self.assertEqual(d['count'], 1)
        it = d['items'][0]
        self.assertEqual(it['task'], 'todo')
        self.assertTrue(it['synced'])
        self.assertEqual(it['payee'], '云南顺通物流')
        # 换成 done 口径 → 该条（RUNNING 任务）不该出现
        r2 = self._post('/api/pk/dingtalk/query',
                        {'userid': 'U-me', 'start': '2026-06-01', 'end': '2026-06-30', 'status': 'done'})
        self.assertEqual(r2.json()['data']['count'], 0)

    @mock.patch('paikuan.dingtalk_client.user_detail', return_value={'name': '郭勇'})
    @mock.patch('paikuan.dingtalk_client.userid_by_mobile', return_value='U-guoyong')
    def test_resolve_user_by_mobile(self, m_uid, m_det):
        r = self._post('/api/pk/dingtalk/resolve-user', {'mobile': '13800001234'})
        users = r.json()['data']['users']
        self.assertEqual(users, [{'userid': 'U-guoyong', 'name': '郭勇'}])

    @mock.patch('paikuan.dingtalk_client.users_by_name',
                return_value=[{'userid': 'A', 'name': '郭勇'}, {'userid': 'B', 'name': '郭勇兵'}])
    def test_resolve_user_by_name_multiple(self, m_names):
        r = self._post('/api/pk/dingtalk/resolve-user', {'name': '郭勇'})
        self.assertEqual(len(r.json()['data']['users']), 2)

    @mock.patch('paikuan.dingtalk_client.list_process_codes', return_value=[{'process_code': 'PC1', 'name': '付款'}])
    @mock.patch('paikuan.dingtalk_client.access_token', return_value='tok')
    def test_connection_lists_templates(self, m_tok, m_codes):
        r = self.client.get('/api/pk/dingtalk/test', **self.auth)
        d = r.json()['data']
        self.assertTrue(d['connected'])
        self.assertEqual(d['templates'][0]['process_code'], 'PC1')
