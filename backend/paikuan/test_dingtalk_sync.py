"""钉钉审批同步：通用字段映射、任务分类、同步/刷新落库、查询分类（client 全 mock）。"""
import json
from decimal import Decimal
from unittest import mock

from django.test import Client, TestCase

from paikuan import dingtalk_client as client
from paikuan import dingtalk_sync as sync
from paikuan.models import ApprovalRecord, DingtalkInstance, PaikuanUser
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

    def test_amount_prefers_heji_keyword(self):
        d = {'form_component_values': [
            {'name': '差旅费', 'value': '100', 'component_type': 'MoneyField'},
            {'name': '住宿费', 'value': '800', 'component_type': 'MoneyField'},
            {'name': '合计', 'value': '900', 'component_type': 'MoneyField'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('900'))

    def test_amount_falls_back_to_table_sum(self):
        # 无独立金额字段 → 明细表金额列求和
        d = {'form_component_values': [
            {'name': '费用明细', 'component_type': 'TableField',
             'value': '[{"费用项目":"交通","金额":"120.50"},{"费用项目":"住宿","金额":"300"}]'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('420.50'))

    def test_amount_table_row_takes_single_column(self):
        # 一行含 不含税金额 + 价税合计 → 只取价税合计，不重复累加
        d = {'form_component_values': [
            {'name': '发票明细', 'component_type': 'TableField',
             'value': '[{"不含税金额":"100","税额":"13","价税合计":"113"},'
                      '{"不含税金额":"200","税额":"26","价税合计":"226"}]'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('339'))    # 113+226，非 452

    def test_amount_prefers_actual_paid_over_gross(self):
        # 报销金额(毛额) 与 实付金额(净额) 并存 → 取实付
        d = {'form_component_values': [
            {'name': '报销金额', 'value': '5000', 'component_type': 'MoneyField'},
            {'name': '抵扣借款', 'value': '-1500', 'component_type': 'MoneyField'},
            {'name': '实付金额', 'value': '3500', 'component_type': 'MoneyField'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('3500'))

    def test_amount_reimbursement_total_field(self):
        # 其他行政费用报销单：明细是 JSON 数组字段 + 独立"总报销金额(元)" → 取总报销金额
        d = {'form_component_values': [
            {'name': '报销明细', 'component_type': 'TableField',
             'value': '[{"报销内容":"宿舍6-8月租","报销金额(元)":"2400.00"}]'},
            {'name': '总报销金额(元)', 'value': '2400.00', 'component_type': 'MoneyField'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('2400.00'))

    def test_amount_reimbursement_detail_only(self):
        # 只有明细数组、无独立总额字段 → 明细按"报销金额"列求和
        d = {'form_component_values': [
            {'name': '费用明细', 'component_type': 'TextField',   # 类型不标准，靠"值是JSON数组"识别
             'value': '[{"报销内容":"A","报销金额(元)":"1000"},{"报销内容":"B","报销金额(元)":"800"}]'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('1800'))

    def test_amount_json_array_not_mangled(self):
        # 明细 JSON 串不能被抠成乱码数字（回归：曾把 JSON 抠成大整数）
        d = {'form_component_values': [
            {'name': '报销明细', 'value': '[{"报销金额(元)":"50.00"}]', 'component_type': 'TextField'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('50.00'))

    def test_amount_and_summary_rowvalue_detail(self):
        # 真实钉钉报销明细：TableField 值是 [{"rowValue":[{label,value,key},...]}]
        detail_json = ('[{"rowValue":[{"label":"申请时间","value":"2026-06-28","key":"DDDateField-1"},'
                       '{"label":"报销内容","value":"零食有鸣项目备用金报销","key":"TextField-1"},'
                       '{"label":"报销金额(元)","value":"3500.00","key":"DDMoneyField-1"}]},'
                       '{"rowValue":[{"label":"报销内容","value":"物料","key":"TextField-2"},'
                       '{"label":"报销金额(元)","value":"1500.00","key":"DDMoneyField-2"}]}]')
        d = {'form_component_values': [
            {'name': '报销明细', 'value': detail_json, 'component_type': 'TableField'},
            {'name': '收款账号', 'value': '罗敏', 'component_type': 'RecipientAccountField'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('5000.00'))     # 3500+1500
        self.assertIn('零食有鸣', sync.build_summary(d))                  # 摘要取明细"报销内容"

    def test_amount_grand_total_non_money_component(self):
        # 合计做成计算/数字控件（非 MoneyField、名字无"金额"）也应被识别为总额
        d = {'form_component_values': [
            {'name': '差旅费', 'value': '1000', 'component_type': 'MoneyField'},
            {'name': '餐饮费', 'value': '500', 'component_type': 'MoneyField'},
            {'name': '费用合计', 'value': '1500', 'component_type': 'NumberField'}]}
        self.assertEqual(sync.extract_amount(d), Decimal('1500'))

    def test_build_summary_picks_reason(self):
        d = {'form_component_values': [
            {'name': '事由', 'value': '出差北京'},
            {'name': '费用类型', 'value': '差旅费'},
            {'name': '报销金额', 'value': '600', 'component_type': 'MoneyField'}]}
        s = sync.build_summary(d)
        self.assertIn('出差北京', s)
        self.assertIn('差旅费', s)

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


class ClientV1Tests(TestCase):
    """新版 v1.0 workflow 接口：实例详情归一、实例ID分页与发起人过滤、模板解析。"""

    @mock.patch('paikuan.dingtalk_client._new')
    def test_get_instance_normalizes_camelcase(self, m_new):
        m_new.return_value = {'result': {
            'businessId': 'B123', 'title': '差旅费报销单', 'originatorUserId': 'U-guo',
            'originatorDeptName': '劳务事业部', 'status': 'COMPLETED', 'result': 'agree',
            'createTime': '2026-03-17T10:00Z',
            'formComponentValues': [
                {'name': '总报销金额(元)', 'value': '600.00', 'componentType': 'MoneyField'}],
            'tasks': [{'userId': 'U-appr', 'status': 'COMPLETED', 'result': 'agree'}],
        }}
        d = client.get_instance('INST-9')
        self.assertEqual(d['_instance_id'], 'INST-9')
        self.assertEqual(d['business_id'], 'B123')
        self.assertEqual(d['originator_userid'], 'U-guo')
        self.assertEqual(d['form_component_values'][0]['component_type'], 'MoneyField')
        self.assertEqual(d['tasks'][0]['userid'], 'U-appr')
        self.assertEqual(d['tasks'][0]['task_status'], 'COMPLETED')
        # 归一后可直接喂给映射层
        self.assertEqual(sync.instance_to_fields(d)['amount'], Decimal('600.00'))
        self.assertEqual(sync.classify(d, 'U-appr'), 'done')

    @mock.patch('paikuan.dingtalk_client._new')
    def test_list_instance_ids_paginates_and_filters_originator(self, m_new):
        m_new.side_effect = [
            {'result': {'list': ['A', 'B'], 'nextToken': 't2'}},
            {'result': {'list': ['C'], 'nextToken': None}},
        ]
        ids = client.list_instance_ids('PC1', 1000, 2000, userid='U-me')
        self.assertEqual(ids, ['A', 'B', 'C'])
        first_body = m_new.call_args_list[0].kwargs['json_body']
        self.assertEqual(first_body['userIds'], ['U-me'])
        self.assertEqual(first_body['processCode'], 'PC1')
        self.assertEqual(m_new.call_args_list[1].kwargs['json_body']['nextToken'], 't2')

    @mock.patch('paikuan.dingtalk_client._new')
    def test_list_instance_ids_no_originator_omits_userids(self, m_new):
        m_new.return_value = {'result': {'list': ['A'], 'nextToken': None}}
        client.list_instance_ids('PC1', 1000, 2000, userid=None)
        self.assertNotIn('userIds', m_new.call_args.kwargs['json_body'])

    @mock.patch('paikuan.dingtalk_client._new')
    def test_templates_by_user_parses_processlist(self, m_new):
        m_new.return_value = {'result': {'processList': [
            {'processCode': 'PC_A', 'name': '差旅费报销单', 'dirName': '财务审批'},
            {'processCode': 'PC_B', 'name': '付款审批'}], 'nextToken': None}}
        tpls = client.templates_by_user('U-guo')
        self.assertEqual([t['process_code'] for t in tpls], ['PC_A', 'PC_B'])
        self.assertEqual(tpls[0]['name'], '差旅费报销单')
        self.assertEqual(tpls[0]['dir_name'], '财务审批')
        self.assertEqual(m_new.call_args.kwargs['params']['userId'], 'U-guo')

    @mock.patch('paikuan.dingtalk_client._new')
    def test_all_templates_omits_userid(self, m_new):
        # userId 省略 → 钉钉返回企业下全部表单（覆盖报销等审批人不可发起的模板）
        m_new.return_value = {'result': {'processList': [
            {'processCode': 'PC_报销', 'name': '差旅费报销单'}], 'nextToken': None}}
        tpls = client.all_templates()
        self.assertEqual(tpls[0]['process_code'], 'PC_报销')
        self.assertNotIn('userId', m_new.call_args.kwargs['params'])

    @mock.patch('paikuan.dingtalk_client._new')
    def test_list_instance_ids_passes_statuses(self, m_new):
        m_new.return_value = {'result': {'list': ['A'], 'nextToken': None}}
        client.list_instance_ids('PC1', 1000, 2000, statuses=['RUNNING'])
        self.assertEqual(m_new.call_args.kwargs['json_body']['statuses'], ['RUNNING'])

    @mock.patch('paikuan.dingtalk_client._new')
    def test_norm_instance_maps_operation_records(self, m_new):
        # 新版无 tasks，用 operationRecords + approverUserIds 表达处理轨迹
        m_new.return_value = {'result': {
            'title': '报销', 'status': 'RUNNING', 'originatorUserId': 'U-emp',
            'approverUserIds': ['U-fin', 'U-mgr'],
            'operationRecords': [
                {'userId': 'U-mgr', 'type': 'EXECUTE_TASK_NORMAL', 'result': 'AGREE'}],
        }}
        d = client.get_instance('INST-X')
        self.assertEqual(d['approver_userids'], ['U-fin', 'U-mgr'])
        self.assertEqual(d['operation_records'][0]['userid'], 'U-mgr')
        # U-mgr 已同意 → done；U-fin 在审批人名单且实例 RUNNING → todo
        self.assertEqual(sync.classify(d, 'U-mgr'), 'done')
        self.assertEqual(sync.classify(d, 'U-fin'), 'todo')
        self.assertEqual(sync.classify(d, 'U-emp'), 'originated')

    def test_time_segments_splits_over_120_days(self):
        day = 24 * 3600 * 1000
        segs = sync._time_segments(0, 200 * day)
        self.assertEqual(len(segs), 2)                       # 200天 → 110 + 90
        self.assertEqual(segs[0], (0, 110 * day))
        self.assertEqual(segs[-1][1], 200 * day)             # 末段覆盖到结束
        self.assertEqual(len(sync._time_segments(0, 30 * day)), 1)


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
    def test_sync_summary_uses_business_content(self, m_get):
        # 转审批记录的摘要 = 业务内容(报销内容)，与查询列表一致，而非钉钉标题
        m_get.return_value = {
            '_instance_id': 'INST-9', 'business_id': 'B9', 'title': '郭勇提交的差旅费报销单',
            'status': 'COMPLETED', 'result': 'agree', 'originator_userid': 'U',
            'operation_records': [], 'approver_userids': [],
            'form_component_values': [
                {'name': '报销明细', 'component_type': 'TableField',
                 'value': '[{"rowValue":[{"label":"报销内容","value":"零食有鸣项目备用金报销"},'
                          '{"label":"报销金额(元)","value":"3500"}]}]'}]}
        self._post('/api/pk/dingtalk/sync', {'instance_ids': ['INST-9']})
        rec = ApprovalRecord.objects.get(dingtalk_instance_id='INST-9')
        self.assertIn('零食有鸣', rec.summary)
        self.assertEqual(rec.amount, Decimal('3500'))

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

    @mock.patch('paikuan.dingtalk_client.all_templates', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_process_codes')
    @mock.patch('paikuan.dingtalk_client.list_instance_ids')
    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_query_filters_by_task_and_marks_synced(self, m_get, m_list, m_codes, m_all):
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

    @mock.patch('paikuan.dingtalk_client.all_templates', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_process_codes',
                return_value=[{'process_code': 'PC1', 'name': '付款审批'}])
    @mock.patch('paikuan.dingtalk_client.list_instance_ids', return_value=[])
    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_query_originator_filter_only_for_originated(self, m_get, m_list, m_codes, m_all):
        # todo：审批人口径，不能按发起人过滤（listids userIds=发起人）
        self._post('/api/pk/dingtalk/query',
                   {'userid': 'U-me', 'start': '2026-06-01', 'end': '2026-06-30', 'status': 'todo'})
        self.assertIsNone(m_list.call_args.args[3])          # userid 不下传
        self.assertEqual(m_list.call_args.args[4], ['RUNNING'])  # todo 收窄到 RUNNING
        # originated：按发起人精准过滤
        self._post('/api/pk/dingtalk/query',
                   {'userid': 'U-me', 'start': '2026-06-01', 'end': '2026-06-30', 'status': 'originated'})
        self.assertEqual(m_list.call_args.args[3], 'U-me')
        self.assertIsNone(m_list.call_args.args[4])          # originated 不限状态

    @mock.patch('paikuan.dingtalk_client.all_templates')
    @mock.patch('paikuan.dingtalk_client.list_process_codes', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_instance_ids')
    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_query_uses_all_company_templates(self, m_get, m_list, m_codes, m_all):
        # 配置为空 → 用「企业全部模板」（覆盖报销等审批人不可发起的表单）
        m_all.return_value = [{'process_code': 'PCX', 'name': '差旅费报销单'}]
        m_list.return_value = ['INST-1']
        m_get.return_value = DETAIL_REIMB
        r = self._post('/api/pk/dingtalk/query',
                       {'userid': 'U-guoyong', 'start': '2026-03-01', 'end': '2026-03-31',
                        'status': 'originated'})   # 郭勇是发起人
        self.assertEqual(r.status_code, 200, r.content)
        m_all.assert_called_once_with()
        d = r.json()['data']
        self.assertEqual(d['count'], 1)
        self.assertEqual(d['items'][0]['template'], '差旅费报销单')

    @mock.patch('paikuan.dingtalk_client.all_templates', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_process_codes', return_value=[])
    def test_query_no_templates_returns_error(self, m_codes, m_all):
        r = self._post('/api/pk/dingtalk/query',
                       {'userid': 'U-x', 'start': '2026-03-01', 'end': '2026-03-31', 'status': 'todo'})
        self.assertEqual(r.status_code, 400, r.content)

    @mock.patch('paikuan.dingtalk_client.all_templates',
                return_value=[{'process_code': 'PC_报销', 'name': '差旅费报销单', 'dir_name': '财务审批'},
                              {'process_code': 'PC_考勤', 'name': '考勤'}])
    @mock.patch('paikuan.dingtalk_client.list_process_codes', return_value=[])
    def test_templates_endpoint_returns_all_company(self, m_codes, m_all):
        r = self._post('/api/pk/dingtalk/templates', {})   # 无需 userid
        d = r.json()['data']
        self.assertEqual(d['count'], 2)
        self.assertIn('PC_报销', [t['process_code'] for t in d['templates']])

    @mock.patch('paikuan.dingtalk_client.all_templates',
                return_value=[{'process_code': 'PC_报销', 'name': '报销'},
                              {'process_code': 'PC_考勤', 'name': '考勤'}])
    @mock.patch('paikuan.dingtalk_client.list_process_codes', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_instance_ids', return_value=[])
    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_query_respects_process_codes_filter(self, m_get, m_list, m_codes, m_all):
        # 只勾选报销 → 只对该模板拉实例，考勤模板不被查询
        self._post('/api/pk/dingtalk/query',
                   {'userid': 'U-guo', 'start': '2026-03-01', 'end': '2026-03-31',
                    'status': 'originated', 'process_codes': ['PC_报销']})
        called_codes = {c.args[0] for c in m_list.call_args_list}
        self.assertEqual(called_codes, {'PC_报销'})

    @mock.patch('paikuan.dingtalk_client.all_templates', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_process_codes',
                return_value=[{'process_code': 'PC1', 'name': '报销'}])
    @mock.patch('paikuan.dingtalk_client.list_instance_ids', return_value=['INST-Z'])
    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_originated_keeps_self_approved(self, m_get, m_list, m_codes, m_all):
        # 他既发起又审批通过：classify 会判 done，但「该员工发起」口径必须保留
        m_get.return_value = {
            '_instance_id': 'INST-Z', 'business_id': 'B', 'title': '本人报销',
            'originator_userid': 'U-me', 'status': 'COMPLETED', 'result': 'agree',
            'form_component_values': [], 'tasks': [],
            'operation_records': [{'userid': 'U-me', 'type': 'EXECUTE_TASK_NORMAL', 'result': 'AGREE'}],
            'approver_userids': ['U-me'],
        }
        self.assertEqual(sync.classify(m_get.return_value, 'U-me'), 'done')   # 单独看是 done
        r = self._post('/api/pk/dingtalk/query',
                       {'userid': 'U-me', 'start': '2026-03-01', 'end': '2026-03-31',
                        'status': 'originated'})
        d = r.json()['data']
        self.assertEqual(d['count'], 1)          # 仍出现在「该员工发起」
        self.assertEqual(d['items'][0]['task'], 'originated')

    @mock.patch('paikuan.dingtalk_client.all_templates', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_process_codes', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_instance_ids', return_value=['INST-1'])
    @mock.patch('paikuan.dingtalk_client.get_instance', return_value=DETAIL_REIMB)
    def test_query_dedups_duplicate_process_codes(self, m_get, m_list, m_codes, m_all):
        # 传入重复 process_code（且不在已取模板集）→ 只查一次、不产生重复行
        r = self._post('/api/pk/dingtalk/query',
                       {'userid': 'U-guoyong', 'start': '2026-03-01', 'end': '2026-03-31',
                        'status': 'originated', 'process_codes': ['PCDUP', 'PCDUP']})
        called = [c.args[0] for c in m_list.call_args_list]
        self.assertEqual(called, ['PCDUP'])            # 只调一次
        self.assertEqual(r.json()['data']['count'], 1)  # 单行，无重复

    @mock.patch('paikuan.dingtalk_client.all_templates', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_process_codes', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_instance_ids', return_value=['INST-1'])
    @mock.patch('paikuan.dingtalk_client.get_instance', return_value=DETAIL_REIMB)
    def test_query_caches_terminal_and_skips_refetch(self, m_get, m_list, m_codes, m_all):
        body = {'userid': 'U-guoyong', 'start': '2026-03-01', 'end': '2026-03-31',
                'status': 'originated', 'process_codes': ['PC1']}
        r1 = self._post('/api/pk/dingtalk/query', body)
        self.assertEqual(r1.json()['data']['count'], 1)
        self.assertEqual(m_get.call_count, 1)                 # 首次拉一次
        self.assertEqual(DingtalkInstance.objects.count(), 1)  # 已落档
        # 第二次同样查询：终态(COMPLETED)实例走本地存档，不再拉钉钉
        r2 = self._post('/api/pk/dingtalk/query', body)
        self.assertEqual(r2.json()['data']['count'], 1)
        self.assertEqual(m_get.call_count, 1)                 # 仍是 1，未重复拉
        self.assertEqual(r2.json()['data']['cache_hits'], 1)

    @mock.patch('paikuan.dingtalk_client.get_instance', return_value=DETAIL_REIMB)
    def test_instance_detail_endpoint(self, m_get):
        r = self._post('/api/pk/dingtalk/instance', {'instance_id': 'INST-1'})
        d = r.json()['data']
        self.assertEqual(d['instance_id'], 'INST-1')
        self.assertEqual(d['applicant'], '郭勇')
        self.assertEqual(d['amount'], '600.00')
        self.assertTrue(any(fld['name'] == '收款账号' for fld in d['form']))
        # 落档后二次读取直接命中本地（终态）
        self.assertEqual(DingtalkInstance.objects.filter(instance_id='INST-1').count(), 1)

    @mock.patch('paikuan.dingtalk_client.get_instance')
    def test_status_sync_from_local_archive(self, m_get):
        # 状态同步只读本地存档，不打钉钉：A按instance_id、B按编号匹配存档；C非21位跳过
        a = ApprovalRecord.objects.create(applicant='甲', department='运输事业部',
            approval_number='202603171454000116103', summary='s', amount=Decimal('1'),
            payee='p', status='pending', dingtalk_instance_id='IID-A')
        b = ApprovalRecord.objects.create(applicant='乙', department='运输事业部',
            approval_number='202603171454000116104', summary='s', amount=Decimal('1'),
            payee='p', status='pending')
        c = ApprovalRecord.objects.create(applicant='丙', department='运输事业部',
            approval_number='NOTDING', summary='s', amount=Decimal('1'), payee='p', status='pending')
        DingtalkInstance.objects.create(instance_id='IID-A', process_code='PC',
            business_id='202603171454000116103', ding_status='COMPLETED', sys_status='approved')
        DingtalkInstance.objects.create(instance_id='IID-B', process_code='PC',
            business_id='202603171454000116104', ding_status='COMPLETED', sys_status='approved')
        r = self._post('/api/pk/dingtalk/status-sync', {'record_ids': [a.id, b.id, c.id]})
        d = r.json()['data']
        self.assertEqual(d['updated'], 2)
        self.assertEqual(m_get.call_count, 0)                   # 不打钉钉
        a.refresh_from_db(); b.refresh_from_db(); c.refresh_from_db()
        self.assertEqual(a.status, 'approved')
        self.assertEqual(b.status, 'approved')
        self.assertEqual(b.dingtalk_instance_id, 'IID-B')       # 按编号匹配后回填实例ID
        self.assertEqual(c.status, 'pending')
        self.assertIn('非21位', ' '.join(s['reason'] for s in d['skipped']))

    def test_status_sync_scheduled_or_archived_not_overwritten(self):
        """已排款/已归档的审批不接受钉钉状态回写(防被拒审批仍挂可付款排款/倒挂)。"""
        # 已排款(approved, scheduled>0):钉钉说 rejected → 跳过不改
        a = ApprovalRecord.objects.create(applicant='甲', department='运输事业部',
            approval_number='202603171454000117001', summary='s', amount=Decimal('1000'),
            payee='p', status='approved', scheduled_amount=Decimal('400'),
            dingtalk_instance_id='IID-S')
        DingtalkInstance.objects.create(instance_id='IID-S', process_code='PC',
            business_id='202603171454000117001', ding_status='COMPLETED', sys_status='rejected')
        r = self._post('/api/pk/dingtalk/status-sync', {'record_ids': [a.id]})
        d = r.json()['data']
        self.assertEqual(d['updated'], 0)
        self.assertIn('已排款/已归档', d['skipped'][0]['reason'])
        a.refresh_from_db()
        self.assertEqual(a.status, 'approved')
        # 未排款 pending → rejected:放行且同步归档
        b = ApprovalRecord.objects.create(applicant='乙', department='运输事业部',
            approval_number='202603171454000117002', summary='s', amount=Decimal('1'),
            payee='p', status='pending', dingtalk_instance_id='IID-T')
        DingtalkInstance.objects.create(instance_id='IID-T', process_code='PC',
            business_id='202603171454000117002', ding_status='COMPLETED', sys_status='rejected')
        r2 = self._post('/api/pk/dingtalk/status-sync', {'record_ids': [b.id]})
        self.assertEqual(r2.json()['data']['updated'], 1)
        b.refresh_from_db()
        self.assertEqual(b.status, 'rejected')
        self.assertTrue(b.archived)   # 终态同步归档,不留 rejected 且未归档的非法态

    def test_status_sync_no_archive_skipped(self):
        # 21位编号但本地无存档 → 跳过并提示先去钉钉同步页查询
        rec = ApprovalRecord.objects.create(applicant='丁', department='运输事业部',
            approval_number='202603171454000116999', summary='s', amount=Decimal('1'),
            payee='p', status='pending')
        r = self._post('/api/pk/dingtalk/status-sync', {'record_ids': [rec.id]})
        d = r.json()['data']
        self.assertEqual(d['updated'], 0)
        self.assertIn('本地无该单据存档', d['skipped'][0]['reason'])

    @mock.patch('paikuan.dingtalk_client.all_templates', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_process_codes', return_value=[])
    @mock.patch('paikuan.dingtalk_client.list_instance_ids', return_value=['INST-2'])
    @mock.patch('paikuan.dingtalk_client.get_instance', return_value=DETAIL_PAY)
    def test_query_all_calibers_at_once(self, m_get, m_list, m_codes, m_all):
        # status=all：一次查回三口径，逐条带 task 角色（DETAIL_PAY 里 U-me 有 RUNNING 任务→todo）
        r = self._post('/api/pk/dingtalk/query',
                       {'userid': 'U-me', 'start': '2026-06-01', 'end': '2026-06-30',
                        'status': 'all', 'process_codes': ['PC1']})
        d = r.json()['data']
        self.assertEqual(d['count'], 1)
        self.assertEqual(d['items'][0]['task'], 'todo')
        # all 口径不按发起人过滤（否则拿不到"待他审批"的）
        self.assertIsNone(m_list.call_args.args[3])

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

    @mock.patch('paikuan.dingtalk_client._post')
    def test_mobile_config_error_surfaces_not_masked(self, m_post):
        # token/凭证类错误必须暴露（502），不能被吞成"查无此人"
        from paikuan.dingtalk_client import DingTalkError
        m_post.side_effect = DingTalkError('不合法的appKey或appSecret')
        r = self._post('/api/pk/dingtalk/resolve-user', {'mobile': '13800001234'})
        self.assertEqual(r.status_code, 502, r.content)

    @mock.patch('paikuan.dingtalk_client._post')
    def test_mobile_not_in_contacts_returns_empty(self, m_post):
        # 手机号不在通讯录（60121）→ 视为查无此人，返回空列表而非报错
        from paikuan.dingtalk_client import DingTalkError
        m_post.side_effect = DingTalkError('找不到该用户', code=60121)
        r = self._post('/api/pk/dingtalk/resolve-user', {'mobile': '13800000000'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['data']['users'], [])
