import io
import json
from datetime import date
from decimal import Decimal

import openpyxl
from django.test import Client, TestCase

from ar.models import (ARPayment, ARProject, ARRecord, CollectionBudget, PaymentBudget,
                       AdvanceRecord, AdvanceWriteoff, Customer,
                       Contract, ContractParty, ContractProject)
from paikuan.models import JobPermission, PaikuanUser
from paikuan.views import DEPARTMENTS, default_job_config, make_token, _invalidate_perm_cache


class ARPermissionRegressionTests(TestCase):
    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '劳务事业部'
        self.other_dept = '运输事业部'

    def tearDown(self):
        _invalidate_perm_cache()

    def make_user(self, phone, job_title, departments=None, role='operator'):
        user = PaikuanUser(
            phone=phone,
            name=f'{job_title} user',
            role=role,
            job_title=job_title,
            departments=departments or [self.dept],
            is_active=True,
            is_approved=True,
        )
        user.set_password('Test123456')
        user.save()
        return user

    def auth(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {make_token(user)}'}

    def json_post(self, url, payload, user):
        return self.client.post(
            url, data=json.dumps(payload), content_type='application/json',
            **self.auth(user))

    def json_put(self, url, payload, user):
        return self.client.put(
            url, data=json.dumps(payload), content_type='application/json',
            **self.auth(user))

    def create_project(self, dept=None, short_name='Project A', delivery_dept=None):
        return ARProject.objects.create(
            customer_name='Contract A',
            short_name=short_name,
            delivery_dept=delivery_dept or dept or self.dept,
            sub_dept='Sub A',
            business_mode='Mode A',
            customer_level='A级',
            sales_contact='Sales A',
            project_manager='PM A',
            has_contract='有',
            contract_date=date(2026, 1, 1),
            reconciliation_days=10,
            invoice_wait_days=5,
            post_invoice_days=15,
            invoice_mode='全额',
            invoice_type='专票',
            tax_rate=Decimal('0.0600'),
        )

    def create_record(self, project=None):
        return ARRecord.objects.create(
            project=project or self.create_project(),
            operation_year=2026,
            operation_month=5,
            estimated_amount=Decimal('1000.00'),
            actual_invoice_amount=Decimal('1060.00'),
            invoice_date=date(2026, 5, 31),
        )

    def project_payload(self):
        return {
            'customer_name': 'Contract B',
            'short_name': 'Project B',
            'delivery_dept': self.dept,
            'sub_dept': 'Sub B',
            'business_mode': 'Mode B',
            'customer_level': 'A级',
            'sales_contact': 'Sales B',
            'project_manager': 'PM B',
            'has_contract': '有',
            'contract_date': '2026-02-01',
            'reconciliation_days': 10,
            'invoice_wait_days': 5,
            'post_invoice_days': 15,
            'invoice_mode': '全额',
            'invoice_type': '专票',
            'tax_rate': '0.06',
        }

    def headers_from_xlsx(self, response):
        wb = openpyxl.load_workbook(io.BytesIO(response.content), data_only=True)
        return [cell.value for cell in wb.active[1]]

    def test_project_post_invoice_days_update_persists(self):
        """票后等待期(post_invoice_days)编辑后应真正落库——回归 settlement_wait_days
        旧列名残留导致 _ar_visible_payload 把该字段从 PUT 载荷里剥掉的问题。"""
        admin = self.make_user('13900000311', 'finance_director', role='super_admin')
        resp = self.json_post('/api/pk/ar/projects', self.project_payload(), admin)
        self.assertEqual(resp.status_code, 200, resp.content)
        pid = resp.json()['data']['id']
        put = self.json_put(f'/api/pk/ar/projects/{pid}', {'post_invoice_days': 30}, admin)
        self.assertEqual(put.status_code, 200, put.content)
        self.assertEqual(put.json()['data']['post_invoice_days'], 30)
        # 重新拉取确认落库（而非仅响应回显）
        got = self.client.get(f'/api/pk/ar/projects/{pid}', **self.auth(admin))
        self.assertEqual(got.json()['data']['post_invoice_days'], 30)

    def test_projects_list_exposes_customer_name_for_advance_autofill(self):
        """预收新增的关联项目下拉用 /ar/projects，选中后以 customer_name 自动带出
        往来单位。该字段须随列表返回且非空，否则前端 pickProject 拿不到值。
        「合同名正名为客户」上线后：新建项目按合同名自动建/挂客户（_autolink_customer），
        列表返回的 customer_id/customer_name 应非空且客户名=合同名。"""
        cfg = default_job_config('cashier')
        cfg['pages']['ar_projects'] = True
        JobPermission.objects.create(job_title='cashier', config=cfg)
        _invalidate_perm_cache('cashier')
        user = self.make_user('13910000099', 'cashier')
        self.create_project(short_name='福佑物流')
        resp = self.client.get('/api/pk/ar/projects', {'q': '福佑物流'}, **self.auth(user))
        self.assertEqual(resp.status_code, 200, resp.content)
        item = resp.json()['data']['items'][0]
        self.assertEqual(item['customer_name'], 'Contract A')
        # 合同名自动正名为客户：customer 非空且名称=合同名
        self.assertIsNotNone(item['customer_id'])
        self.assertEqual(item['customer_name'], 'Contract A')

    def test_cashier_page_access_cannot_write_ar_records(self):
        cfg = default_job_config('cashier')
        cfg['pages']['ar_projects'] = True
        JobPermission.objects.create(job_title='cashier', config=cfg)
        _invalidate_perm_cache('cashier')
        user = self.make_user('13910000001', 'cashier')
        project = self.create_project()
        record = self.create_record(project)

        checks = [
            self.json_post('/api/pk/ar/projects', self.project_payload(), user),
            self.json_post('/api/pk/ar/records', {
                'project_id': project.id,
                'operation_year': 2026,
                'operation_month': 6,
                'estimated_amount': '100.00',
            }, user),
            self.json_post('/api/pk/ar/budget/collection', {
                'short_name': 'Budget A',
                'expected_date': '2026-06-10',
                'delivery_dept': self.dept,
                'amount': '100.00',
            }, user),
            self.json_post(f'/api/pk/ar/records/{record.id}/payments', {
                'amount': '100.00',
                'payment_date': '2026-06-11',
            }, user),
        ]

        self.assertTrue(all(resp.status_code == 403 for resp in checks))

    def test_budget_detail_is_department_scoped_and_delete_requires_permission(self):
        user = self.make_user('13910000002', 'finance_bp')
        own_budget = CollectionBudget.objects.create(
            short_name='Own Budget',
            expected_date=date(2026, 6, 1),
            delivery_dept=self.dept,
            amount=Decimal('100.00'),
        )
        other_budget = CollectionBudget.objects.create(
            short_name='Other Budget',
            expected_date=date(2026, 6, 1),
            delivery_dept=self.other_dept,
            amount=Decimal('200.00'),
        )

        self.assertEqual(
            self.client.get(f'/api/pk/ar/budget/collection/{other_budget.id}', **self.auth(user)).status_code,
            403,
        )
        self.assertEqual(
            self.json_put(f'/api/pk/ar/budget/collection/{other_budget.id}', {'amount': '300.00'}, user).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(f'/api/pk/ar/budget/collection/{other_budget.id}', **self.auth(user)).status_code,
            403,
        )

        ok_resp = self.json_put(
            f'/api/pk/ar/budget/collection/{own_budget.id}',
            {'amount': '150.00'},
            user,
        )
        self.assertEqual(ok_resp.status_code, 200)
        self.assertEqual(
            self.client.delete(f'/api/pk/ar/budget/collection/{own_budget.id}', **self.auth(user)).status_code,
            403,
        )

    def test_ar_exports_respect_hidden_field_permissions(self):
        cfg = default_job_config('cashier')
        cfg['pages']['ar_projects'] = True
        cfg['ar_view']['p_customer_name'] = False
        JobPermission.objects.create(job_title='cashier', config=cfg)
        _invalidate_perm_cache('cashier')
        user = self.make_user('13910000003', 'cashier')
        project = self.create_project()
        self.create_record(project)

        project_resp = self.client.get('/api/pk/ar/projects/export', **self.auth(user))
        record_resp = self.client.get('/api/pk/ar/records/export', **self.auth(user))

        self.assertEqual(project_resp.status_code, 200)
        self.assertNotIn('合同名称', self.headers_from_xlsx(project_resp))
        self.assertEqual(record_resp.status_code, 200)
        record_headers = self.headers_from_xlsx(record_resp)
        self.assertNotIn('税额', record_headers)
        self.assertNotIn('账实差额调整', record_headers)

    def test_hidden_payments_field_blocks_payment_subresource(self):
        cfg = default_job_config('finance_bp')
        cfg['ar_view']['r_payments'] = False
        JobPermission.objects.create(job_title='finance_bp', config=cfg)
        _invalidate_perm_cache('finance_bp')
        user = self.make_user('13910000004', 'finance_bp')
        record = self.create_record()

        get_resp = self.client.get(f'/api/pk/ar/records/{record.id}/payments', **self.auth(user))
        post_resp = self.json_post(f'/api/pk/ar/records/{record.id}/payments', {
            'amount': '100.00',
            'payment_date': '2026-06-11',
        }, user)

        self.assertEqual(get_resp.status_code, 403)
        self.assertEqual(post_resp.status_code, 403)

    def test_payment_signal_recomputes_tax_and_outstanding_amount(self):
        record = self.create_record()

        self.assertEqual(record.tax_amount, Decimal('60.00'))
        # outstanding is based on estimated_amount (1000), not invoice amount
        self.assertEqual(record.outstanding_amount, Decimal('1000.00'))

        ARPayment.objects.create(
            ar_record=record,
            payment_no=1,
            amount=Decimal('160.00'),
            payment_date=date(2026, 6, 10),
        )

        record.refresh_from_db()
        self.assertEqual(record.tax_amount, Decimal('60.00'))
        self.assertEqual(record.outstanding_amount, Decimal('840.00'))

    def test_data_health_flags_stale_and_negative_records(self):
        admin = self.make_user('13900000099', 'finance_director', role='super_admin')
        project = self.create_project()

        # healthy record — should not be flagged
        healthy = self.create_record(project)
        ARPayment.objects.create(ar_record=healthy, payment_no=1,
                                 amount=Decimal('300.00'), payment_date=date(2026, 6, 1))

        # stale record — tamper stored outstanding directly (bypassing recompute)
        stale = ARRecord.objects.create(project=project, operation_year=2026,
                                        operation_month=6, estimated_amount=Decimal('770000.00'))
        ARPayment.objects.create(ar_record=stale, payment_no=1,
                                 amount=Decimal('100000.00'), payment_date=date(2026, 6, 2))
        ARRecord.objects.filter(pk=stale.pk).update(outstanding_amount=Decimal('999999.00'))

        # negative record — payments exceed estimated (raw insert to bypass validation)
        neg = ARRecord.objects.create(project=project, operation_year=2026,
                                      operation_month=7, estimated_amount=Decimal('270000.00'))
        ARPayment.objects.bulk_create([
            ARPayment(ar_record=neg, payment_no=1, amount=Decimal('100000.00'),
                      payment_date=date(2026, 6, 3)),
            ARPayment(ar_record=neg, payment_no=2, amount=Decimal('200000.00'),
                      payment_date=date(2026, 6, 4)),
        ])

        resp = self.client.get('/api/pk/ar/records/health', **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertTrue(data['has_issues'])
        self.assertEqual(data['stale_count'], 1)
        self.assertEqual(data['negative_count'], 1)
        self.assertEqual(data['stale'][0]['id'], stale.id)
        self.assertEqual(data['negative'][0]['id'], neg.id)
        self.assertEqual(data['negative'][0]['deficit'], '30000.00')

        # bulk recompute fixes the stale one and reports the negative one as failed
        resp = self.json_post('/api/pk/ar/records/recompute',
                              {'ids': [stale.id, neg.id]}, admin)
        self.assertEqual(resp.status_code, 200)
        result = resp.json()['data']
        self.assertEqual(result['fixed'], 1)
        self.assertEqual(len(result['failed']), 1)
        self.assertEqual(result['failed'][0]['id'], neg.id)

        stale.refresh_from_db()
        self.assertEqual(stale.outstanding_amount, Decimal('670000.00'))

    def test_project_update_syncs_budget_dept_fields(self):
        project = self.create_project()
        cb = CollectionBudget.objects.create(
            project_no=project.project_no, short_name=project.short_name,
            expected_date=date(2026, 6, 1), delivery_dept=project.delivery_dept,
            sub_dept=project.sub_dept or '', amount=Decimal('100000'))
        pb = PaymentBudget.objects.create(
            project_no=project.project_no, short_name=project.short_name,
            expected_date=date(2026, 6, 1), delivery_dept=project.delivery_dept,
            sub_dept=project.sub_dept or '', amount=Decimal('50000'))

        # Change delivery_dept and sub_dept on the project — signal should propagate
        project.delivery_dept = '运输事业部'
        project.sub_dept = '新二级部门'
        project.save()

        cb.refresh_from_db(); pb.refresh_from_db()
        self.assertEqual(cb.delivery_dept, '运输事业部')
        self.assertEqual(cb.sub_dept, '新二级部门')
        self.assertEqual(pb.delivery_dept, '运输事业部')
        self.assertEqual(pb.sub_dept, '新二级部门')

    def test_budget_import_corrects_wrong_fields_from_project(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        admin = self.make_user('13900000088', 'finance_director', role='super_admin')
        project = self.create_project()  # short_name 'Project A', dept 劳务事业部, sub 'Sub A'

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['项目编号(可选)', '项目简称/摘要*', '预计收款日期(YYYY-MM-DD)*',
                   '二级部门', '交付部门', '金额*', '备注'])
        # correct short_name, but WRONG project_no / sub_dept / delivery_dept
        ws.append(['WRONG-001', 'Project A', '2026-06-15',
                   '错误二级部门', '运输事业部', 100000, '测试'])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        upload = SimpleUploadedFile(
            'b.xlsx', buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

        resp = self.client.post('/api/pk/ar/budget/collection/import',
                                data={'file': upload}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['data']
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['corrected'], 1)

        cb = CollectionBudget.objects.get(short_name='Project A')
        # All three wrong fields overridden with the project's authoritative values
        self.assertEqual(cb.delivery_dept, project.delivery_dept)
        self.assertEqual(cb.sub_dept, project.sub_dept)
        self.assertEqual(cb.project_no, project.project_no)

    def test_budget_import_accepts_excel_date_cell(self):
        """回归：Excel 把日期列识别为日期类型时（openpyxl 返回 datetime），
        导入不应再报"预计日期无效"。这是"按模板填都报错"的根因。"""
        import datetime as dt
        from django.core.files.uploadedfile import SimpleUploadedFile
        admin = self.make_user('13900000201', 'finance_director', role='super_admin')
        self.create_project(short_name='日期格式项目', delivery_dept='劳务事业部')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['项目编号(可选)', '项目简称/摘要*', '预计收款日期*',
                   '二级部门', '交付部门', '金额*', '备注'])
        # 关键：日期作为真正的 datetime 单元格写入（模拟 Excel 自动日期识别）
        ws.append(['', '日期格式项目', dt.datetime(2026, 6, 15), '', '劳务事业部', 50000, ''])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        resp = self.client.post('/api/pk/ar/budget/collection/import',
                                {'file': SimpleUploadedFile('b.xlsx', buf.read())},
                                **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        d = resp.json()['data']
        self.assertEqual(d['created'], 1, d.get('errors'))
        self.assertEqual(d['errors'], [])
        self.assertEqual(str(CollectionBudget.objects.get().expected_date), '2026-06-15')

    def test_budget_import_accepts_multiple_date_formats(self):
        """回归：模板支持的多种日期格式（斜杠/中文/紧凑/2位年）导入均应通过。"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        admin = self.make_user('13900000203', 'finance_director', role='super_admin')
        self.create_project(short_name='多格式项目', delivery_dept='劳务事业部')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['项目编号(可选)', '项目简称/摘要*', '预计收款日期*',
                   '二级部门', '交付部门', '金额*', '备注'])
        for d in ['2026/6/15', '2026年6月15日', '20260615', '26-6-15']:
            ws.append(['', '多格式项目', d, '', '劳务事业部', 1000, ''])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        resp = self.client.post('/api/pk/ar/budget/collection/import',
                                {'file': SimpleUploadedFile('b.xlsx', buf.read())},
                                **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        d = resp.json()['data']
        self.assertEqual(d['created'], 4, d.get('errors'))
        self.assertEqual(d['errors'], [])
        dates = sorted(str(b.expected_date) for b in CollectionBudget.objects.all())
        self.assertEqual(dates, ['2026-06-15'] * 4)

    def test_ar_record_import_rejects_whole_file_on_error(self):
        """应收明细导入：任一行【格式错误】→ 整表拒绝、零写入、列出全部问题；
        全部合法 → 整表写入。（找不到的项目不算错误，写入阶段自动建草稿）"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        admin = self.make_user('13900000301', 'finance_director', role='super_admin')
        self.create_project(short_name='应收导入项目', delivery_dept='劳务事业部')
        HEAD = ['项目简称*', '运作年*', '运作月*', '预估上账金额', '实际开票金额',
                '税额(差额模式手填)', '开票日期', '账实差额调整', '回款金额', '回款时间', '备注']

        # ① 含格式错误：第2行金额非法 → 整表拒绝（第3行项目不存在不算错误）
        wb = openpyxl.Workbook(); ws = wb.active; ws.append(HEAD)
        ws.append(['应收导入项目', 2026, 1, 'abc', '', '', '', '', '', '', ''])   # 金额非法
        ws.append(['不存在的项目', 2026, 1, 1000, '', '', '', '', '', '', ''])    # 项目缺失(自动建草稿)
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        resp = self.client.post('/api/pk/ar/records/import',
                                {'file': SimpleUploadedFile('r.xlsx', buf.read())}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        d = resp.json()['data']
        self.assertTrue(d['rejected'])
        self.assertEqual(d['created'], 0)
        self.assertEqual(len(d['errors']), 1, d['errors'])   # 仅金额格式 1 处
        self.assertEqual(ARRecord.objects.count(), 0)   # 零写入

        # ② 全部合法 → 写入
        wb2 = openpyxl.Workbook(); ws2 = wb2.active; ws2.append(HEAD)
        ws2.append(['应收导入项目', 2026, 1, 100000, 100000, '', '2026-01-15', 0, 30000, '2026-01-20', ''])
        ws2.append(['应收导入项目', 2026, 2, 80000, '', '', '', '', '', '', '同月可多条'])
        buf2 = io.BytesIO(); wb2.save(buf2); buf2.seek(0)
        resp2 = self.client.post('/api/pk/ar/records/import',
                                 {'file': SimpleUploadedFile('r2.xlsx', buf2.read())}, **self.auth(admin))
        d2 = resp2.json()['data']
        self.assertFalse(d2.get('rejected'))
        self.assertEqual(d2['created'], 2, d2.get('errors'))
        self.assertEqual(ARRecord.objects.count(), 2)

    def test_budget_import_skips_template_tip_and_example_rows(self):
        """回归：模板自带的"说明行"(★开头)与"示例行"(含示例标记)应被跳过，
        不会被当作真实数据导入或产生日期错误。"""
        from ar.views import _budget_template
        from django.test import RequestFactory
        from django.core.files.uploadedfile import SimpleUploadedFile
        admin = self.make_user('13900000202', 'finance_director', role='super_admin')
        # 直接下载模板，原样回传导入——应零创建、零错误
        rf = RequestFactory()
        req = rf.get('/api/pk/ar/budget/collection/template')
        req.pk_uid = admin.id; req.pk_role = 'super_admin'; req.pk_depts = []
        tmpl_resp = _budget_template(req, 'collection')
        buf = io.BytesIO(tmpl_resp.content); buf.seek(0)
        resp = self.client.post('/api/pk/ar/budget/collection/import',
                                {'file': SimpleUploadedFile('t.xlsx', buf.read())},
                                **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        d = resp.json()['data']
        self.assertEqual(d['created'], 0)
        self.assertEqual(d['errors'], [])

    def test_records_filter_by_payment_date_and_unpaid(self):
        admin = self.make_user('13900000077', 'finance_director', role='super_admin')
        project = self.create_project()

        paid = self.create_record(project)
        ARPayment.objects.create(ar_record=paid, payment_no=1,
                                 amount=Decimal('200.00'), payment_date=date(2026, 6, 10))
        # second record with no payments at all
        unpaid = ARRecord.objects.create(project=project, operation_year=2026,
                                         operation_month=7, estimated_amount=Decimal('500.00'))

        def ids(params):
            resp = self.client.get('/api/pk/ar/records', params, **self.auth(admin))
            self.assertEqual(resp.status_code, 200)
            return {r['id'] for r in resp.json()['data']['items']}

        # pay date range covering the payment → only the paid record
        in_range = ids({'pay_start': '2026-06-01', 'pay_end': '2026-06-30'})
        self.assertIn(paid.id, in_range)
        self.assertNotIn(unpaid.id, in_range)

        # pay date range outside the payment → neither record
        out_range = ids({'pay_start': '2026-08-01', 'pay_end': '2026-08-31'})
        self.assertNotIn(paid.id, out_range)

        # unpaid filter → only the record with no payments
        unpaid_only = ids({'pay_status': 'unpaid'})
        self.assertIn(unpaid.id, unpaid_only)
        self.assertNotIn(paid.id, unpaid_only)

        # date range + pay_include_unpaid=1 → OR: June-paid OR outstanding_amount>0
        combined = ids({'pay_start': '2026-06-01', 'pay_end': '2026-06-30', 'pay_include_unpaid': '1'})
        self.assertIn(paid.id, combined)    # has June payment
        self.assertIn(unpaid.id, combined)  # outstanding > 0

    def test_records_server_side_sort(self):
        """服务端排序：白名单字段升/降序、空值排末尾、非法 sort 安全回退。"""
        admin = self.make_user('13900000079', 'finance_director', role='super_admin')
        project = self.create_project()
        # actual_invoice_amount 可空且非派生，用于验证升降序 + 空值排末尾
        a = ARRecord.objects.create(project=project, operation_year=2026, operation_month=5,
                                    estimated_amount=Decimal('300.00'), actual_invoice_amount=Decimal('30.00'))
        b = ARRecord.objects.create(project=project, operation_year=2026, operation_month=5,
                                    estimated_amount=Decimal('100.00'), actual_invoice_amount=Decimal('10.00'))
        c = ARRecord.objects.create(project=project, operation_year=2026, operation_month=5,
                                    estimated_amount=Decimal('200.00'))  # actual_invoice 为空

        def order(params):
            resp = self.client.get('/api/pk/ar/records', params, **self.auth(admin))
            self.assertEqual(resp.status_code, 200, resp.content)
            return [r['id'] for r in resp.json()['data']['items']]

        self.assertEqual(order({'sort': 'estimated'}), [b.id, c.id, a.id])      # 升序
        self.assertEqual(order({'sort': '-estimated'}), [a.id, c.id, b.id])     # 降序
        # 空值排末尾：invoiced 升序时非空在前(b=10,a=30)、空值 c 殿后
        asc_inv = order({'sort': 'invoiced'})
        self.assertEqual(asc_inv, [b.id, a.id, c.id])
        self.assertEqual(asc_inv[-1], c.id)
        # 非法 sort 键安全忽略（仍返回三条，不报错）
        self.assertEqual(len(order({'sort': 'drop_table'})), 3)

    def test_bulk_delete_by_ids_and_by_filter(self):
        """批量删除：显式 ids + 选择全部筛选集(all+conditions)，级联回款、受权限约束。"""
        import json as _json
        admin = self.make_user('13900000083', 'finance_director', role='super_admin')
        project = self.create_project()
        r1 = ARRecord.objects.create(project=project, operation_year=2026, operation_month=5,
                                     estimated_amount=Decimal('100.00'))
        ARPayment.objects.create(ar_record=r1, payment_no=1, amount=Decimal('10.00'),
                                 payment_date=date(2026, 5, 9))
        r2 = ARRecord.objects.create(project=project, operation_year=2026, operation_month=6,
                                     estimated_amount=Decimal('200.00'))
        r3 = ARRecord.objects.create(project=project, operation_year=2026, operation_month=7,
                                     estimated_amount=Decimal('300.00'))

        # 显式 ids 删除 r1（级联其回款）
        resp = self.client.post('/api/pk/ar/records/bulk-delete',
                                data=_json.dumps({'ids': [r1.id]}),
                                content_type='application/json', **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['deleted'], 1)
        self.assertFalse(ARRecord.objects.filter(pk=r1.id).exists())
        self.assertEqual(ARPayment.objects.filter(ar_record_id=r1.id).count(), 0)

        # all + 条件：删除 预估>150 的全部（r2/r3），r 不在条件外
        conds = _json.dumps([{'t': 'amt', 'field': 'estimated_amount', 'op': 'gt', 'value': 150}])
        resp = self.client.post(f'/api/pk/ar/records/bulk-delete?conditions={conds}',
                                data=_json.dumps({'all': True}),
                                content_type='application/json', **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['deleted'], 2)
        self.assertEqual(ARRecord.objects.filter(pk__in=[r2.id, r3.id]).count(), 0)

    def test_project_bulk_delete_by_ids_and_filter(self):
        """项目批量删除：显式 ids + 选择全部筛选集(all+dept)，级联应收明细、受权限约束。"""
        import json as _json
        admin = self.make_user('13900000084', 'finance_director', role='super_admin')
        p1 = self.create_project(short_name='P1')
        p2 = self.create_project(short_name='P2')
        p3 = self.create_project(short_name='P3', delivery_dept=self.other_dept)
        ARRecord.objects.create(project=p1, operation_year=2026, operation_month=5,
                                estimated_amount=Decimal('100.00'))

        # 显式 ids 删除 p1（级联其应收明细）
        resp = self.client.post('/api/pk/ar/projects/bulk-delete',
                                data=_json.dumps({'ids': [p1.id]}),
                                content_type='application/json', **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['deleted'], 1)
        self.assertFalse(ARProject.objects.filter(pk=p1.id).exists())
        self.assertEqual(ARRecord.objects.filter(project_id=p1.id).count(), 0)

        # all + dept 筛选：仅删本部门(p2)，p3 在其他部门不受影响
        resp = self.client.post(f'/api/pk/ar/projects/bulk-delete?dept={self.dept}',
                                data=_json.dumps({'all': True}),
                                content_type='application/json', **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['deleted'], 1)
        self.assertFalse(ARProject.objects.filter(pk=p2.id).exists())
        self.assertTrue(ARProject.objects.filter(pk=p3.id).exists())

    def test_project_bulk_delete_requires_permission(self):
        """无删除权限不得批量删除项目。"""
        import json as _json
        cfg = default_job_config('cashier')
        cfg['pages']['ar_projects'] = True
        cfg['can_delete'] = False
        JobPermission.objects.create(job_title='cashier', config=cfg)
        _invalidate_perm_cache('cashier')
        user = self.make_user('13910000097', 'cashier')
        p = self.create_project()
        resp = self.client.post('/api/pk/ar/projects/bulk-delete',
                                data=_json.dumps({'ids': [p.id]}),
                                content_type='application/json', **self.auth(user))
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertTrue(ARProject.objects.filter(pk=p.id).exists())

    def test_bulk_delete_allowed_with_can_delete(self):
        """非超管但 can_delete=true 应被允许批量删除（验证授权链路正确）。"""
        import json as _json
        cfg = default_job_config('cashier')
        cfg['pages']['ar_records'] = True
        cfg['can_delete'] = True
        JobPermission.objects.create(job_title='cashier', config=cfg)
        _invalidate_perm_cache('cashier')
        user = self.make_user('13910000098', 'cashier')
        rec = self.create_record(self.create_project())
        resp = self.client.post('/api/pk/ar/records/bulk-delete',
                                data=_json.dumps({'ids': [rec.id]}),
                                content_type='application/json', **self.auth(user))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['deleted'], 1)
        self.assertFalse(ARRecord.objects.filter(pk=rec.id).exists())

    def test_bulk_delete_requires_permission(self):
        """无删除权限不得批量删除。"""
        import json as _json
        cfg = default_job_config('cashier')
        cfg['pages']['ar_records'] = True
        cfg['can_delete'] = False
        JobPermission.objects.create(job_title='cashier', config=cfg)
        _invalidate_perm_cache('cashier')
        user = self.make_user('13910000099', 'cashier')
        rec = self.create_record(self.create_project())
        resp = self.client.post('/api/pk/ar/records/bulk-delete',
                                data=_json.dumps({'ids': [rec.id]}),
                                content_type='application/json', **self.auth(user))
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertTrue(ARRecord.objects.filter(pk=rec.id).exists())

    def test_conditions_match_any_or_logic(self):
        """统一条件 + match=all(且)/any(或)：维度/金额条件组合。"""
        import json as _json
        admin = self.make_user('13900000082', 'finance_director', role='super_admin')
        project = self.create_project()
        # a: 未开票(无开票额、有未收余额)，预估 100
        a = ARRecord.objects.create(project=project, operation_year=2026, operation_month=5,
                                    estimated_amount=Decimal('100.00'))
        # b: 已开票，预估 200
        b = ARRecord.objects.create(project=project, operation_year=2026, operation_month=6,
                                    estimated_amount=Decimal('200.00'),
                                    actual_invoice_amount=Decimal('200.00'))

        def ids(conditions, match=None):
            p = {'conditions': _json.dumps(conditions)}
            if match:
                p['match'] = match
            resp = self.client.get('/api/pk/ar/records', p, **self.auth(admin))
            self.assertEqual(resp.status_code, 200, resp.content)
            return {r['id'] for r in resp.json()['data']['items']}

        conds = [{'t': 'dim', 'field': 'invoice_status', 'value': '未开票'},
                 {'t': 'amt', 'field': 'estimated_amount', 'op': 'gt', 'value': 150}]
        # 且：未开票 且 预估>150 → 空（a未开票但=100，b预估200但已开票）
        self.assertEqual(ids(conds, 'all'), set())
        # 或：未开票 或 预估>150 → a(未开票) + b(预估200) = 两条
        self.assertEqual(ids(conds, 'any'), {a.id, b.id})

    def test_conditions_builder_date_and_amount(self):
        """条件构建器：金额运算符(≠0) + 回款日期相对区间(含/不含本月)。"""
        import json as _json
        admin = self.make_user('13900000081', 'finance_director', role='super_admin')
        project = self.create_project()
        today = date.today()
        this_m = date(today.year, today.month, 15)
        last_m = (date(today.year - 1, 12, 15) if today.month == 1
                  else date(today.year, today.month - 1, 15))

        # r1: 有未收余额(outstanding>0)，本月回款
        r1 = ARRecord.objects.create(project=project, operation_year=2026, operation_month=5,
                                     estimated_amount=Decimal('500.00'))
        ARPayment.objects.create(ar_record=r1, payment_no=1, amount=Decimal('100.00'), payment_date=this_m)
        # r2: 上月回款，无未收（全额回款）
        r2 = ARRecord.objects.create(project=project, operation_year=2026, operation_month=6,
                                     estimated_amount=Decimal('200.00'))
        ARPayment.objects.create(ar_record=r2, payment_no=1, amount=Decimal('200.00'), payment_date=last_m)

        def ids(conditions):
            resp = self.client.get('/api/pk/ar/records',
                                   {'conditions': _json.dumps(conditions)}, **self.auth(admin))
            self.assertEqual(resp.status_code, 200, resp.content)
            return {r['id'] for r in resp.json()['data']['items']}

        # 未收金额≠0 → 仅 r1
        ne0 = ids([{'t': 'amt', 'field': 'outstanding_amount', 'op': 'ne0'}])
        self.assertEqual(ne0, {r1.id})
        # 回款日期含本月 → 仅 r1
        in_m = ids([{'t': 'date', 'field': 'payment_date', 'range': 'this_month'}])
        self.assertEqual(in_m, {r1.id})
        # 回款日期不含本月 → 排除有本月回款的 r1 → 仅 r2
        not_m = ids([{'t': 'date', 'field': 'payment_date', 'range': 'this_month', 'exclude': True}])
        self.assertEqual(not_m, {r2.id})
        # 组合：回款不含本月 + 未收≠0 → 空（r2 无未收，r1 被日期排除）
        combo = ids([{'t': 'date', 'field': 'payment_date', 'range': 'this_month', 'exclude': True},
                     {'t': 'amt', 'field': 'outstanding_amount', 'op': 'ne0'}])
        self.assertEqual(combo, set())
        # 非法 conditions 安全忽略（返回全部 2 条）
        self.assertEqual(len(ids('not-a-list' and [{'t': 'bogus'}])), 2)

    def test_invoice_status_unbilled_filter_excludes_settled(self):
        # 开票跟踪「未开票」筛选不得包含已结清（已全额回款）的记录，与
        # ARRecord.invoice_status 属性一致（已结清优先级高于未开票）。
        admin = self.make_user('13900000078', 'finance_director', role='super_admin')
        project = self.create_project()

        # 未开票且仍有未收余额 → 应出现在「未开票」结果中
        unbilled = ARRecord.objects.create(project=project, operation_year=2026,
                                           operation_month=7, estimated_amount=Decimal('500.00'))

        # 未开票但已全额回款 → invoice_status 计为「已结清」，不应出现在「未开票」
        settled = ARRecord.objects.create(project=project, operation_year=2026,
                                          operation_month=8, estimated_amount=Decimal('300.00'))
        ARPayment.objects.create(ar_record=settled, payment_no=1,
                                 amount=Decimal('300.00'), payment_date=date(2026, 8, 15))
        settled.refresh_from_db()
        self.assertLessEqual(settled.outstanding_amount, Decimal('0'))
        self.assertEqual(settled.invoice_status, '已结清')

        resp = self.client.get('/api/pk/ar/records', {'invoice_status': '未开票'}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        result_ids = {r['id'] for r in resp.json()['data']['items']}
        self.assertIn(unbilled.id, result_ids)
        self.assertNotIn(settled.id, result_ids)

        # KPI「待开票」笔数同样应排除已结清记录
        kpi = self.client.get('/api/pk/ar/records/kpi', **self.auth(admin))
        self.assertEqual(kpi.status_code, 200, kpi.content)
        self.assertEqual(kpi.json()['data']['invoice']['pending'], 1)

    def test_summary_not_inflated_by_multiple_payments(self):
        admin = self.make_user('13900000055', 'finance_director', role='super_admin')
        project = self.create_project()
        rec = ARRecord.objects.create(project=project, operation_year=2026,
                                      operation_month=8, estimated_amount=Decimal('1000.00'))
        # two payments on the same record — must not multiply estimated/count
        ARPayment.objects.create(ar_record=rec, payment_no=1,
                                 amount=Decimal('300.00'), payment_date=date(2026, 9, 1))
        ARPayment.objects.create(ar_record=rec, payment_no=2,
                                 amount=Decimal('200.00'), payment_date=date(2026, 9, 5))

        # filter by pay date range that matches both payments (JOIN fanout risk)
        resp = self.client.get('/api/pk/ar/records',
                               {'pay_start': '2026-09-01', 'pay_end': '2026-09-30'},
                               **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        s = resp.json()['data']['summary']
        self.assertEqual(s['count'], 1)
        self.assertEqual(Decimal(s['estimated']), Decimal('1000.00'))   # not 2000
        self.assertEqual(Decimal(s['collected']), Decimal('500.00'))    # 300 + 200

    def test_summary_period_fields_month_and_week(self):
        import calendar as cal
        admin = self.make_user('13900000044', 'finance_director', role='super_admin')
        project = self.create_project()

        # Record whose due_date is the last day of 2026-06
        last_june = date(2026, 6, 30)
        rec_june = ARRecord.objects.create(
            project=project, operation_year=2026, operation_month=6,
            estimated_amount=Decimal('1000.00'))
        ARRecord.objects.filter(pk=rec_june.pk).update(due_date=last_june)

        # Record whose due_date is in a different month (July)
        rec_july = ARRecord.objects.create(
            project=project, operation_year=2026, operation_month=7,
            estimated_amount=Decimal('2000.00'))
        ARRecord.objects.filter(pk=rec_july.pk).update(due_date=date(2026, 7, 15))

        # Payment on 2026-07-01 → inside the week (6/29~7/5) but NOT in June month
        ARPayment.objects.create(ar_record=rec_june, payment_no=1,
                                 amount=Decimal('400.00'), payment_date=date(2026, 7, 1))
        # Payment on 2026-06-15 → inside June month but NOT in the week
        ARPayment.objects.create(ar_record=rec_june, payment_no=2,
                                 amount=Decimal('250.00'), payment_date=date(2026, 6, 15))

        # Request with year=2026 month=6 → ref_date=2026-06-30 (month end)
        resp = self.client.get('/api/pk/ar/records', {'year': 2026, 'month': 6},
                               **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        s = resp.json()['data']['summary']

        # 当期应收：due_date=2026-06-30 落在6月 → rec_june 的 estimated_amount=1000
        self.assertEqual(Decimal(s['month_curr_est']), Decimal('1000.00'))
        self.assertEqual(s['ref_month'], '2026年6月')
        # 当期已收：payment_date 在6月(06-15) 且 ar_record.due_date>=mo_start(06-30>=06-01) → 250
        self.assertEqual(Decimal(s['month_curr_collected']), Decimal('250.00'))
        # 逾期应收：rec_june due_date=06-30 不早于mo_start(06-01) → 0（无逾期记录）
        self.assertEqual(Decimal(s['month_overdue_est']), Decimal('0'))
        # 逾期已收：payment_date 在6月(06-15) 且 ar_record.due_date<mo_start(06-30<06-01? No) → 0
        self.assertEqual(Decimal(s['month_overdue_collected']), Decimal('0'))

        # week window for 2026-06-30 (Tuesday): Mon=2026-06-29, Sun=2026-07-05
        # rec_june has due_date=2026-06-30 (in that week) → week_est includes it
        self.assertEqual(Decimal(s['week_est']), Decimal('1000.00'))
        # week_collected: payment on 2026-07-01 is in the week → 400 (not the 06-15 one)
        self.assertEqual(Decimal(s['week_collected']), Decimal('400.00'))

        # ── 关键回归：历史月份筛选（早于今天）时 ref_date 不应被 today 覆盖 ──
        # year=2026 month=6 is before today (2026-05-30... actually June is after May, let's use a past year)
        # Use July record filtered by pay_end=2026-03-31 (before today=2026-05-30)
        # ref_candidates should be [2026-03-31], ref_date=2026-03-31 (not today=May)
        resp2 = self.client.get('/api/pk/ar/records', {'pay_end': '2026-03-31'},
                                **self.auth(admin))
        self.assertEqual(resp2.status_code, 200)
        s2 = resp2.json()['data']['summary']
        # ref_date must be 2026-03-31 (March), not today (May)
        self.assertEqual(s2['ref_date'], '2026-03-31')
        self.assertEqual(s2['ref_month'], '2026年3月')
        self.assertEqual(s2['ref_week'], '3/30~4/5')  # week of 2026-03-31 (Mon3/30~Sun4/5)
        # 基准周非今天所在周 → 标签为"该周"
        self.assertEqual(s2['ref_week_label'], '该周')

        # 无任何日期筛选 → ref_date=today，周标签为"本周"
        resp3 = self.client.get('/api/pk/ar/records', **self.auth(admin))
        s3 = resp3.json()['data']['summary']
        self.assertEqual(s3['ref_date'], date.today().isoformat())
        self.assertEqual(s3['ref_week_label'], '本周')

    def test_records_search_matches_project_manager(self):
        admin = self.make_user('13900000066', 'finance_director', role='super_admin')
        project = self.create_project()  # project_manager 'PM A'
        rec = self.create_record(project)

        resp = self.client.get('/api/pk/ar/records', {'q': 'PM A'}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(rec.id, {r['id'] for r in resp.json()['data']['items']})


class AdvanceModuleTests(TestCase):
    """预收预付：CRUD、核销重算、导入、现金流打通、KPI、权限遮蔽。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '劳务事业部'

    def tearDown(self):
        _invalidate_perm_cache()

    def make_user(self, phone, job_title, departments=None, role='operator'):
        u = PaikuanUser(phone=phone, name=f'{job_title} u', role=role, job_title=job_title,
                        departments=departments or [self.dept], is_active=True, is_approved=True)
        u.set_password('Test123456'); u.save()
        return u

    def auth(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {make_token(user)}'}

    def create_project(self, short_name='预收项目A'):
        return ARProject.objects.create(
            customer_name='合同A', short_name=short_name, delivery_dept=self.dept,
            sales_contact='Sales A', project_manager='PM A', has_contract='有',
            contract_date=date(2026, 1, 1))

    def post(self, url, payload, user):
        return self.client.post(url, data=json.dumps(payload),
                                content_type='application/json', **self.auth(user))

    # ── 创建（挂项目 / 独立往来单位）────────────────────────────────────────────
    def test_create_with_and_without_project(self):
        admin = self.make_user('13911100001', 'finance_director', role='super_admin')
        proj = self.create_project()
        # 挂项目：交付部门自动取项目部门
        r1 = self.post('/api/pk/ar/advances', {
            'direction': '预收', 'project_id': proj.id, 'counterparty': '客户甲',
            'occur_year': 2026, 'occur_month': 3, 'occur_date': '2026-03-10',
            'advance_amount': 100000}, admin)
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertEqual(r1.json()['data']['delivery_dept'], self.dept)
        self.assertEqual(r1.json()['data']['balance_amount'], '100000.00')
        # 独立（预付供应商，无项目，手填部门）
        r2 = self.post('/api/pk/ar/advances', {
            'direction': '预付', 'delivery_dept': self.dept, 'counterparty': '供应商乙',
            'occur_year': 2026, 'occur_month': 3, 'occur_date': '2026-03-12',
            'advance_amount': 50000}, admin)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertIsNone(r2.json()['data']['project_id'])
        # 方向校验
        bad = self.post('/api/pk/ar/advances', {
            'direction': 'X', 'delivery_dept': self.dept, 'occur_year': 2026,
            'occur_month': 3, 'advance_amount': 1}, admin)
        self.assertEqual(bad.status_code, 400)

    # ── 核销重算 + 余额非负 ────────────────────────────────────────────────────
    def test_writeoff_recompute_and_non_negative(self):
        admin = self.make_user('13911100002', 'finance_director', role='super_admin')
        rec = AdvanceRecord.objects.create(
            direction='预收', delivery_dept=self.dept, counterparty='客户甲',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 10),
            advance_amount=Decimal('100000'))
        # 核销 30000 → 余额 70000，部分核销
        w = self.post(f'/api/pk/ar/advances/{rec.id}/writeoffs',
                      {'amount': 30000, 'writeoff_date': '2026-04-01'}, admin)
        self.assertEqual(w.status_code, 200, w.content)
        rec.refresh_from_db()
        self.assertEqual(rec.balance_amount, Decimal('70000.00'))
        self.assertEqual(rec.written_off_amount, Decimal('30000.00'))
        self.assertEqual(rec.writeoff_status, '部分核销')
        # 超额核销 → 拒绝（余额不能为负）
        over = self.post(f'/api/pk/ar/advances/{rec.id}/writeoffs',
                         {'amount': 999999, 'writeoff_date': '2026-04-02'}, admin)
        self.assertEqual(over.status_code, 400, over.content)
        rec.refresh_from_db()
        self.assertEqual(rec.balance_amount, Decimal('70000.00'))  # unchanged
        # 删除核销 → 余额恢复
        wid = w.json()['data']['id']
        d = self.client.delete(f'/api/pk/ar/advances/{rec.id}/writeoffs/{wid}', **self.auth(admin))
        self.assertEqual(d.status_code, 200)
        rec.refresh_from_db()
        self.assertEqual(rec.balance_amount, Decimal('100000.00'))
        self.assertEqual(rec.writeoff_status, '未核销')

    # ── 导入（含核销）+ 模板可解析 ─────────────────────────────────────────────
    def test_import_creates_advances_and_writeoff(self):
        admin = self.make_user('13911100003', 'finance_director', role='super_admin')
        self.create_project(short_name='预收项目A')
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(['方向(预收/预付)*', '项目简称', '交付部门', '往来单位*', '发生年*', '发生月*',
                   '款项日期', '预收/预付金额', '预计核销日期', '核销金额', '核销日期', '备注'])
        ws.append(['预收', '预收项目A', '', '客户甲', 2026, 3, '2026-03-10',
                   100000, '2026-06-30', 40000, '2026-04-01', ''])
        ws.append(['预付', '', self.dept, '供应商乙', 2026, 3, '2026-03-12', 50000, '', '', '', ''])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        buf.name = 'adv.xlsx'
        resp = self.client.post('/api/pk/ar/advances/import', {'file': buf}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['created'], 2)
        recv = AdvanceRecord.objects.get(direction='预收', counterparty='客户甲')
        self.assertEqual(recv.balance_amount, Decimal('60000.00'))  # 100000 - 40000
        self.assertEqual(recv.delivery_dept, self.dept)

    # ── 现金流打通：净额含预收(流入)与预付(流出) ───────────────────────────────
    def test_cashflow_includes_advances(self):
        admin = self.make_user('13911100004', 'finance_director', role='super_admin')
        AdvanceRecord.objects.create(direction='预收', delivery_dept=self.dept,
                                     counterparty='客户甲', occur_year=2026, occur_month=3,
                                     occur_date=date(2026, 3, 10), advance_amount=Decimal('100000'))
        AdvanceRecord.objects.create(direction='预付', delivery_dept=self.dept,
                                     counterparty='供应商乙', occur_year=2026, occur_month=3,
                                     occur_date=date(2026, 3, 12), advance_amount=Decimal('30000'))
        resp = self.client.get('/api/pk/ar/cashflow',
                               {'start_date': '2026-03-01', 'end_date': '2026-03-31',
                                'depts': self.dept}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        t = resp.json()['data']['totals']
        self.assertEqual(t['advance_received'][0], 100000.0)
        self.assertEqual(t['advance_paid'][0], 30000.0)
        self.assertEqual(t['inflow'][0], 100000.0)
        self.assertEqual(t['outflow'][0], 30000.0)
        self.assertEqual(t['net'][0], 70000.0)

    # ── KPI 分预收/预付 ────────────────────────────────────────────────────────
    def test_kpi_blocks(self):
        admin = self.make_user('13911100005', 'finance_director', role='super_admin')
        rec = AdvanceRecord.objects.create(direction='预收', delivery_dept=self.dept,
                                           counterparty='客户甲', occur_year=2026, occur_month=3,
                                           occur_date=date(2026, 3, 10), advance_amount=Decimal('100000'))
        AdvanceWriteoff.objects.create(advance_record=rec, writeoff_no=1,
                                       amount=Decimal('25000'), writeoff_date=date(2026, 4, 1))
        rec.recompute_derived()
        resp = self.client.get('/api/pk/ar/advances/kpi', **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        b = resp.json()['data']['预收']
        self.assertEqual(b['advance_amount'], 100000.0)
        self.assertEqual(b['written_off'], 25000.0)
        self.assertEqual(b['balance'], 75000.0)
        self.assertEqual(b['writeoff_rate'], 25.0)

    # ── 字段级权限遮蔽：隐藏金额 ───────────────────────────────────────────────
    def test_field_permission_masks_amount(self):
        # 自定义职务：隐藏 adv_amount
        cfg = default_job_config('operator')
        cfg['ar_view']['adv_amount'] = False
        JobPermission.objects.update_or_create(job_title='operator', defaults={'config': cfg})
        _invalidate_perm_cache()
        user = self.make_user('13911100006', 'operator', role='operator')
        AdvanceRecord.objects.create(direction='预收', delivery_dept=self.dept,
                                     counterparty='客户甲', occur_year=2026, occur_month=3,
                                     occur_date=date(2026, 3, 10), advance_amount=Decimal('100000'))
        resp = self.client.get('/api/pk/ar/advances', **self.auth(user))
        self.assertEqual(resp.status_code, 200, resp.content)
        row = resp.json()['data']['items'][0]
        self.assertIsNone(row['advance_amount'])      # masked
        self.assertEqual(row['counterparty'], '客户甲')  # still visible

    # ── 可用预收/预付联动查询（供回款/排款页弹出）─────────────────────────────
    def test_available_lookup_by_project(self):
        admin = self.make_user('13911100007', 'finance_director', role='super_admin')
        proj = self.create_project()
        # 一笔部分核销的预收（余额 70000）+ 一笔已核销的预收（余额 0，应排除）
        a1 = AdvanceRecord.objects.create(
            direction='预收', project=proj, delivery_dept=self.dept, counterparty='客户甲',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 10),
            advance_amount=Decimal('100000'))
        AdvanceWriteoff.objects.create(advance_record=a1, writeoff_no=1,
                                       amount=Decimal('30000'), writeoff_date=date(2026, 4, 1))
        a1.recompute_derived()
        a2 = AdvanceRecord.objects.create(
            direction='预收', project=proj, delivery_dept=self.dept, counterparty='客户甲',
            occur_year=2026, occur_month=2, occur_date=date(2026, 2, 1),
            advance_amount=Decimal('20000'))
        AdvanceWriteoff.objects.create(advance_record=a2, writeoff_no=1,
                                       amount=Decimal('20000'), writeoff_date=date(2026, 3, 1))
        a2.recompute_derived()
        # 一笔预付（方向不同，预收查询应排除）
        AdvanceRecord.objects.create(
            direction='预付', project=proj, delivery_dept=self.dept, counterparty='供应商乙',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 12),
            advance_amount=Decimal('50000'))
        resp = self.client.get('/api/pk/ar/advances/available',
                               {'project_id': proj.id, 'direction': '预收'}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['count'], 1)                 # 仅 a1 仍有余额
        self.assertEqual(d['total_balance'], '70000.00')
        self.assertEqual(d['items'][0]['id'], a1.id)
        # 预付方向
        resp_p = self.client.get('/api/pk/ar/advances/available',
                                 {'project_id': proj.id, 'direction': '预付'}, **self.auth(admin))
        self.assertEqual(resp_p.json()['data']['total_balance'], '50000.00')

    # ── 预收核销自动转回款（冲减应收）+ 现金流不重复计 ─────────────────────────
    def _ar_record(self, proj, est, year=2026, month=2):
        return ARRecord.objects.create(
            project=proj, operation_year=year, operation_month=month,
            estimated_amount=Decimal(str(est)))

    def test_writeoff_offsets_ar_record_and_reverses_on_delete(self):
        admin = self.make_user('13911100010', 'finance_director', role='super_admin')
        proj = self.create_project()
        ar = self._ar_record(proj, 100000)
        adv = AdvanceRecord.objects.create(
            direction='预收', project=proj, delivery_dept=self.dept, counterparty='客户甲',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 10),
            advance_amount=Decimal('100000'))
        # 核销 40000 并冲抵该应收明细
        w = self.post(f'/api/pk/ar/advances/{adv.id}/writeoffs',
                      {'amount': 40000, 'writeoff_date': '2026-03-20',
                       'ar_record_id': ar.id}, admin)
        self.assertEqual(w.status_code, 200, w.content)
        wj = w.json()['data']
        self.assertEqual(wj['ar_record_id'], ar.id)
        self.assertIsNotNone(wj['ar_payment_id'])
        adv.refresh_from_db(); ar.refresh_from_db()
        self.assertEqual(adv.balance_amount, Decimal('60000.00'))   # 预收余额减少
        self.assertEqual(ar.outstanding_amount, Decimal('60000.00'))  # 应收 outstanding 减少
        pay = ARPayment.objects.get(pk=wj['ar_payment_id'])
        self.assertEqual(pay.source, '预收抵扣')
        self.assertEqual(pay.amount, Decimal('40000.00'))
        # 现金流：预收 100000 计入流入；预收抵扣 40000 不重复计现金（collected 排除）
        resp = self.client.get('/api/pk/ar/cashflow',
                               {'start_date': '2026-03-01', 'end_date': '2026-03-31',
                                'depts': self.dept}, **self.auth(admin))
        t = resp.json()['data']['totals']
        self.assertEqual(t['advance_received'][0], 100000.0)
        self.assertEqual(t['collected'][0], 0.0)       # 预收抵扣不计入现金回款
        self.assertEqual(t['inflow'][0], 100000.0)     # 不重复计
        # 删除核销 → 应收 outstanding 与预收余额均恢复，预收抵扣回款被删除
        d = self.client.delete(
            f'/api/pk/ar/advances/{adv.id}/writeoffs/{wj["id"]}', **self.auth(admin))
        self.assertEqual(d.status_code, 200, d.content)
        adv.refresh_from_db(); ar.refresh_from_db()
        self.assertEqual(adv.balance_amount, Decimal('100000.00'))
        self.assertEqual(ar.outstanding_amount, Decimal('100000.00'))
        self.assertFalse(ARPayment.objects.filter(pk=wj['ar_payment_id']).exists())

    def test_offset_amount_cannot_exceed_outstanding(self):
        admin = self.make_user('13911100011', 'finance_director', role='super_admin')
        proj = self.create_project()
        ar = self._ar_record(proj, 30000)
        adv = AdvanceRecord.objects.create(
            direction='预收', project=proj, delivery_dept=self.dept, counterparty='客户甲',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 10),
            advance_amount=Decimal('100000'))
        w = self.post(f'/api/pk/ar/advances/{adv.id}/writeoffs',
                      {'amount': 40000, 'writeoff_date': '2026-03-20',
                       'ar_record_id': ar.id}, admin)
        self.assertEqual(w.status_code, 400, w.content)
        ar.refresh_from_db(); adv.refresh_from_db()
        self.assertEqual(ar.outstanding_amount, Decimal('30000.00'))  # 未变
        self.assertEqual(adv.balance_amount, Decimal('100000.00'))    # 未生成核销

    def test_offset_only_for_receivable_direction(self):
        admin = self.make_user('13911100012', 'finance_director', role='super_admin')
        proj = self.create_project()
        ar = self._ar_record(proj, 100000)
        adv = AdvanceRecord.objects.create(
            direction='预付', project=proj, delivery_dept=self.dept, counterparty='供应商乙',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 10),
            advance_amount=Decimal('100000'))
        w = self.post(f'/api/pk/ar/advances/{adv.id}/writeoffs',
                      {'amount': 10000, 'writeoff_date': '2026-03-20',
                       'ar_record_id': ar.id}, admin)
        self.assertEqual(w.status_code, 400, w.content)

    def test_offset_payment_cannot_be_deleted_directly(self):
        admin = self.make_user('13911100013', 'finance_director', role='super_admin')
        proj = self.create_project()
        ar = self._ar_record(proj, 100000)
        adv = AdvanceRecord.objects.create(
            direction='预收', project=proj, delivery_dept=self.dept, counterparty='客户甲',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 10),
            advance_amount=Decimal('100000'))
        w = self.post(f'/api/pk/ar/advances/{adv.id}/writeoffs',
                      {'amount': 40000, 'writeoff_date': '2026-03-20',
                       'ar_record_id': ar.id}, admin)
        pid = w.json()['data']['ar_payment_id']
        d = self.client.delete(f'/api/pk/ar/records/{ar.id}/payments/{pid}', **self.auth(admin))
        self.assertEqual(d.status_code, 400, d.content)  # 须经核销删除

    # ── 可用预收：本项目 ∪ 散单客户匹配 ────────────────────────────────────────
    def test_available_union_project_and_customer(self):
        admin = self.make_user('13911100014', 'finance_director', role='super_admin')
        proj = ARProject.objects.create(
            customer_name='合同P', short_name='项目P', delivery_dept=self.dept,
            sales_contact='S', project_manager='M')
        other = ARProject.objects.create(
            customer_name='合同Q', short_name='项目Q', delivery_dept=self.dept,
            sales_contact='S', project_manager='M')
        # A1：挂本项目
        a1 = AdvanceRecord.objects.create(
            direction='预收', project=proj, delivery_dept=self.dept, counterparty='ACME物流',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 1),
            advance_amount=Decimal('50000'))
        # A2：散单（无项目），往来单位 == 客户名（精确匹配）
        a2 = AdvanceRecord.objects.create(
            direction='预收', delivery_dept=self.dept, counterparty='ACME物流',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 2),
            advance_amount=Decimal('30000'))
        # A2b：散单但往来单位仅部分包含客户名 → 精确匹配下排除
        AdvanceRecord.objects.create(
            direction='预收', delivery_dept=self.dept, counterparty='ACME物流有限公司',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 5),
            advance_amount=Decimal('11111'))
        # A3：散单但别的客户 → 排除
        AdvanceRecord.objects.create(
            direction='预收', delivery_dept=self.dept, counterparty='别的客户',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 3),
            advance_amount=Decimal('99999'))
        # A4：挂另一项目（同客户名）→ 排除（不能冲抵本项目应收）
        AdvanceRecord.objects.create(
            direction='预收', project=other, delivery_dept=self.dept, counterparty='ACME物流',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 4),
            advance_amount=Decimal('77777'))
        resp = self.client.get('/api/pk/ar/advances/available',
                               {'project_id': proj.id, 'customer': 'ACME物流',
                                'direction': '预收'}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['count'], 2)
        self.assertEqual(d['total_balance'], '80000.00')
        ids = {it['id'] for it in d['items']}
        self.assertEqual(ids, {a1.id, a2.id})
        mt = {it['id']: it['match_type'] for it in d['items']}
        self.assertEqual(mt[a1.id], 'project')
        self.assertEqual(mt[a2.id], 'customer')

    def test_offset_with_standalone_advance(self):
        admin = self.make_user('13911100015', 'finance_director', role='super_admin')
        proj = ARProject.objects.create(
            customer_name='合同R', short_name='项目R', delivery_dept=self.dept,
            sales_contact='S', project_manager='M')
        ar = self._ar_record(proj, 100000)
        adv = AdvanceRecord.objects.create(   # 散单预收，无项目
            direction='预收', delivery_dept=self.dept, counterparty='ACME',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 1),
            advance_amount=Decimal('60000'))
        w = self.post(f'/api/pk/ar/advances/{adv.id}/writeoffs',
                      {'amount': 60000, 'writeoff_date': '2026-03-20',
                       'ar_record_id': ar.id}, admin)
        self.assertEqual(w.status_code, 200, w.content)
        adv.refresh_from_db(); ar.refresh_from_db()
        self.assertEqual(adv.balance_amount, Decimal('0.00'))
        self.assertEqual(ar.outstanding_amount, Decimal('40000.00'))
        pay = ARPayment.objects.get(pk=w.json()['data']['ar_payment_id'])
        self.assertEqual(pay.source, '预收抵扣')

    def test_offsettable_records_by_customer(self):
        admin = self.make_user('13911100016', 'finance_director', role='super_admin')
        proj = ARProject.objects.create(
            customer_name='ACME物流', short_name='项目S', delivery_dept=self.dept,
            sales_contact='S', project_manager='M')
        other = ARProject.objects.create(
            customer_name='别的客户', short_name='项目T', delivery_dept=self.dept,
            sales_contact='S', project_manager='M')
        r1 = self._ar_record(proj, 50000)
        self._ar_record(other, 70000)  # 别的客户 → 不应出现
        resp = self.client.get('/api/pk/ar/advances/offsettable',
                               {'customer': 'ACME物流'}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200, resp.content)
        items = resp.json()['data']['items']
        self.assertEqual([it['id'] for it in items], [r1.id])

    def test_available_lookup_respects_field_permission(self):
        cfg = default_job_config('operator')
        cfg['ar_view']['adv_amount'] = False
        JobPermission.objects.update_or_create(job_title='operator', defaults={'config': cfg})
        _invalidate_perm_cache()
        user = self.make_user('13911100008', 'operator', role='operator')
        proj = self.create_project()
        AdvanceRecord.objects.create(
            direction='预收', project=proj, delivery_dept=self.dept, counterparty='客户甲',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 10),
            advance_amount=Decimal('100000'))
        resp = self.client.get('/api/pk/ar/advances/available',
                               {'project_id': proj.id}, **self.auth(user))
        self.assertEqual(resp.status_code, 403)         # 金额字段被遮蔽 → 拒绝


class ProjectImportRoundtripTests(TestCase):
    """项目台账导入：导出表头(不带*)应能再次导入；缺合同名时回退项目简称。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '供应链事业部'
        u = PaikuanUser(phone='13922200001', name='Admin', role='super_admin',
                        job_title='finance_director', departments=[self.dept],
                        is_active=True, is_approved=True)
        u.set_password('Test123456'); u.save()
        self.token = make_token(u)

    def tearDown(self):
        _invalidate_perm_cache()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def _upload(self, ws_rows):
        wb = openpyxl.Workbook(); ws = wb.active
        for r in ws_rows:
            ws.append(r)
        buf = io.BytesIO(); wb.save(buf); buf.seek(0); buf.name = 'proj.xlsx'
        return self.client.post('/api/pk/ar/projects/import', {'file': buf}, **self.auth())

    def test_export_style_headers_without_asterisk_import(self):
        # 导出文件表头：无 *、开票模式/专票普票为短名 —— 之前会整表静默跳过
        headers = ['项目编号', '客户名称', '项目简称', '交付部门', '二级部门',
                   '业务模式', '客户等级', '销售对接人', '项目负责人', '共享业务', '有无合同',
                   '签订日期', '合同对账期(天)', '开票等待期(天)', '票后等待期(天)', '总账期(天)',
                   '开票模式', '专票/普票', '税率', '备注']
        row = ['GYL-X', '南京福佑物流合同', '南京福佑', self.dept, '',
               '整车', 'A级', '张三', '李四', '是', '有',
               '2026-01-01', 30, 0, 60, 90, '全额', '专票', '0.06', '']
        resp = self._upload([headers, row])
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['created'], 1, d)
        self.assertEqual(d['skipped'], 0, d)
        p = ARProject.objects.get(short_name='南京福佑')
        self.assertEqual(p.customer_name, '南京福佑物流合同')
        self.assertEqual(p.invoice_type, '专票')

    def test_missing_customer_name_falls_back_to_short_name(self):
        headers = ['合同名称*', '项目简称*', '交付部门*', '销售对接人*', '项目负责人*']
        row = ['', '南京福佑', self.dept, '张三', '李四']
        resp = self._upload([headers, row])
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['created'], 1, d)
        p = ARProject.objects.get(short_name='南京福佑')
        self.assertEqual(p.customer_name, '南京福佑')   # 回退用项目简称

    def test_same_customer_name_different_short_names_not_merged(self):
        """1合同多项目：同一合同名下不同项目简称必须各自建档，不能被合并去重
        （回归：去重主键须为项目简称+部门，而非合同名+部门）。"""
        headers = ['合同名称*', '项目简称*', '交付部门*', '销售对接人*', '项目负责人*']
        rows = [
            ['南京福佑在线电子商务有限公司', '南京福佑', self.dept, '张三', '李四'],
            ['南京福佑在线电子商务有限公司', '福佑顺心', self.dept, '张三', '李四'],
        ]
        resp = self._upload([headers] + rows)
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['created'], 2, d)      # 两个项目都应创建
        self.assertEqual(d['updated'], 0, d)
        names = set(ARProject.objects.filter(
            customer_name='南京福佑在线电子商务有限公司').values_list('short_name', flat=True))
        self.assertEqual(names, {'南京福佑', '福佑顺心'})

    def test_reimport_same_short_name_updates_not_duplicates(self):
        """同项目简称+部门重复导入应更新而非重复建档。"""
        headers = ['合同名称*', '项目简称*', '交付部门*', '销售对接人*', '项目负责人*', '业务模式']
        self._upload([headers, ['合同A', '项目X', self.dept, '张三', '李四', '整车']])
        resp = self._upload([headers, ['合同A改名', '项目X', self.dept, '王五', '赵六', '零担']])
        d = resp.json()['data']
        self.assertEqual(d['created'], 0, d)
        self.assertEqual(d['updated'], 1, d)
        self.assertEqual(ARProject.objects.filter(short_name='项目X', delivery_dept=self.dept).count(), 1)

    def test_row_with_data_but_no_name_reports_error(self):
        headers = ['合同名称*', '项目简称*', '交付部门*', '销售对接人*', '项目负责人*']
        row = ['', '', self.dept, '张三', '李四']   # 有数据但无名称
        resp = self._upload([headers, row])
        d = resp.json()['data']
        self.assertEqual(d['created'], 0, d)
        self.assertEqual(len(d['errors']), 1, d)
        self.assertIn('客户名称', d['errors'][0])


class InvoiceBatchTests(TestCase):
    """合并开票批次号：批量设置、按批次查询汇总、单条编辑。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '供应链事业部'
        u = PaikuanUser(phone='13933300001', name='Admin', role='super_admin',
                        job_title='finance_director', departments=[self.dept],
                        is_active=True, is_approved=True)
        u.set_password('Test123456'); u.save()
        self.token = make_token(u)
        self.proj = ARProject.objects.create(
            customer_name='合并开票测试合同', short_name='批次测试项目',
            delivery_dept=self.dept, sales_contact='S', project_manager='M')

    def tearDown(self):
        _invalidate_perm_cache()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def _rec(self, month, estimated=100000):
        r = ARRecord(project=self.proj, operation_year=2026, operation_month=month,
                     estimated_amount=Decimal(str(estimated)))
        r.save()
        return r

    def _put(self, url, payload):
        return self.client.put(url, data=json.dumps(payload),
                               content_type='application/json', **self.auth())

    def _post(self, url, payload):
        return self.client.post(url, data=json.dumps(payload),
                                content_type='application/json', **self.auth())

    def test_batch_assign_by_ids(self):
        r1 = self._rec(1); r2 = self._rec(2)
        resp = self._post('/api/pk/ar/records/batch-assign',
                          {'ids': [r1.id, r2.id], 'invoice_batch_no': 'PF-2026-001'})
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['updated'], 2)
        r1.refresh_from_db(); r2.refresh_from_db()
        self.assertEqual(r1.invoice_batch_no, 'PF-2026-001')
        self.assertEqual(r2.invoice_batch_no, 'PF-2026-001')

    def test_batch_assign_clear(self):
        r1 = self._rec(3)
        r1.invoice_batch_no = 'PF-2026-001'; r1.save()
        resp = self._post('/api/pk/ar/records/batch-assign',
                          {'ids': [r1.id], 'invoice_batch_no': ''})
        self.assertEqual(resp.status_code, 200)
        r1.refresh_from_db()
        self.assertEqual(r1.invoice_batch_no, '')

    def test_invoice_batches_endpoint(self):
        r1 = self._rec(4); r2 = self._rec(5)
        r1.invoice_batch_no = 'PF-2026-002'; r1.save()
        r2.invoice_batch_no = 'PF-2026-002'; r2.save()
        resp = self.client.get('/api/pk/ar/records/invoice-batches', **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        batches = resp.json()['data']['batches']
        self.assertEqual(len(batches), 1)
        b = batches[0]
        self.assertEqual(b['batch_no'], 'PF-2026-002')
        self.assertEqual(b['count'], 2)
        self.assertAlmostEqual(float(b['estimated']), 200000.0, places=2)

    def test_put_record_sets_batch_no(self):
        r1 = self._rec(6)
        resp = self._put(f'/api/pk/ar/records/{r1.id}',
                         {'invoice_batch_no': 'PF-2026-003'})
        self.assertEqual(resp.status_code, 200, resp.content)
        r1.refresh_from_db()
        self.assertEqual(r1.invoice_batch_no, 'PF-2026-003')

class ContractAndImportAmbiguityTests(TestCase):
    """合同实体（1合同多客户多项目 / 1项目多合同）+ 应收导入歧义处理。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '供应链事业部'
        u = PaikuanUser(phone='13944400001', name='Admin', role='super_admin',
                        job_title='finance_director', departments=[self.dept],
                        is_active=True, is_approved=True)
        u.set_password('Test123456'); u.save()
        self.token = make_token(u)

    def tearDown(self):
        _invalidate_perm_cache()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def _proj(self, short_name, customer_name='合同X'):
        return ARProject.objects.create(
            customer_name=customer_name, short_name=short_name,
            delivery_dept=self.dept, sales_contact='S', project_manager='M')

    def _upload_records(self, head, rows):
        from django.core.files.uploadedfile import SimpleUploadedFile
        wb = openpyxl.Workbook(); ws = wb.active; ws.append(head)
        for r in rows:
            ws.append(r)
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        return self.client.post('/api/pk/ar/records/import',
                                {'file': SimpleUploadedFile('r.xlsx', buf.read())}, **self.auth())

    # ── 合同多对多 ────────────────────────────────────────────────────────────
    def test_contract_many_customers_and_projects(self):
        c1 = Customer.objects.create(name='客户甲')
        c2 = Customer.objects.create(name='客户乙')
        p1 = self._proj('项目A'); p2 = self._proj('项目B')
        ct = Contract.objects.create(name='联合服务合同', delivery_dept=self.dept)
        ContractParty.objects.create(contract=ct, customer=c1, role='main')
        ContractParty.objects.create(contract=ct, customer=c2, role='sub')
        ContractProject.objects.create(contract=ct, project=p1)
        ContractProject.objects.create(contract=ct, project=p2)
        self.assertEqual(ct.customers.count(), 2)
        self.assertEqual(ct.projects.count(), 2)
        # 1项目多合同
        ct2 = Contract.objects.create(name='补充协议', delivery_dept=self.dept)
        ContractProject.objects.create(contract=ct2, project=p1)
        self.assertEqual(p1.contracts.count(), 2)

    # ── 导入歧义：多个同名项目且未消歧 → 整表拒绝 + 候选项 ─────────────────────
    def test_import_ambiguous_same_name_rejects_with_candidates(self):
        self._proj('同名项目', customer_name='合同甲')
        self._proj('同名项目', customer_name='合同乙')
        HEAD = ['项目编号', '项目简称*', '客户名称', '运作年*', '运作月*', '预估上账金额',
                '实际开票金额', '税额(差额模式手填)', '开票日期', '账实差额调整',
                '回款金额', '回款时间', '备注']
        d = self._upload_records(HEAD, [
            ['', '同名项目', '', 2026, 1, 100000, '', '', '', '', '', '', ''],
        ]).json()['data']
        self.assertTrue(d['rejected'])
        self.assertEqual(d['created'], 0)
        self.assertEqual(len(d['ambiguities']), 1)
        self.assertEqual(len(d['ambiguities'][0]['candidates']), 2)
        self.assertEqual(ARRecord.objects.count(), 0)

    # ── 项目编号精确指定 → 消除歧义、正常写入 ─────────────────────────────────
    def test_import_project_no_disambiguates(self):
        p1 = self._proj('同名项目', customer_name='合同甲')
        self._proj('同名项目', customer_name='合同乙')
        HEAD = ['项目编号', '项目简称*', '客户名称', '运作年*', '运作月*', '预估上账金额',
                '实际开票金额', '税额(差额模式手填)', '开票日期', '账实差额调整',
                '回款金额', '回款时间', '备注']
        d = self._upload_records(HEAD, [
            [p1.project_no, '同名项目', '', 2026, 1, 100000, '', '', '', '', '', '', ''],
        ]).json()['data']
        self.assertFalse(d.get('rejected'), d)
        self.assertEqual(d['created'], 1)
        self.assertEqual(ARRecord.objects.filter(project=p1).count(), 1)

    # ── 客户名称消歧 → 正常写入 ──────────────────────────────────────────────
    def test_import_customer_hint_disambiguates(self):
        self._proj('同名项目', customer_name='合同甲')
        p2 = self._proj('同名项目', customer_name='合同乙')
        HEAD = ['项目编号', '项目简称*', '客户名称', '运作年*', '运作月*', '预估上账金额',
                '实际开票金额', '税额(差额模式手填)', '开票日期', '账实差额调整',
                '回款金额', '回款时间', '备注']
        d = self._upload_records(HEAD, [
            ['', '同名项目', '合同乙', 2026, 1, 100000, '', '', '', '', '', '', ''],
        ]).json()['data']
        self.assertFalse(d.get('rejected'), d)
        self.assertEqual(d['created'], 1)
        self.assertEqual(ARRecord.objects.filter(project=p2).count(), 1)

    # ── 项目编号填了但不存在 → 拒绝 + 指导 ───────────────────────────────────
    def test_import_bad_project_no_rejects(self):
        self._proj('唯一项目')
        HEAD = ['项目编号', '项目简称*', '客户名称', '运作年*', '运作月*', '预估上账金额',
                '实际开票金额', '税额(差额模式手填)', '开票日期', '账实差额调整',
                '回款金额', '回款时间', '备注']
        d = self._upload_records(HEAD, [
            ['YS-99999999-9999', '唯一项目', '', 2026, 1, 100000, '', '', '', '', '', '', ''],
        ]).json()['data']
        self.assertTrue(d['rejected'])
        self.assertEqual(len(d['bad_nos']), 1)
        self.assertEqual(ARRecord.objects.count(), 0)

    # ── 纯增量：同项目同月多行不合并 ─────────────────────────────────────────
    def test_import_is_additive_no_merge(self):
        p = self._proj('增量项目')
        HEAD = ['项目编号', '项目简称*', '客户名称', '运作年*', '运作月*', '预估上账金额',
                '实际开票金额', '税额(差额模式手填)', '开票日期', '账实差额调整',
                '回款金额', '回款时间', '备注']
        d = self._upload_records(HEAD, [
            ['', '增量项目', '', 2026, 1, 100000, '', '', '', '', '', '', '第一笔'],
            ['', '增量项目', '', 2026, 1, 80000, '', '', '', '', '', '', '同月第二笔'],
        ]).json()['data']
        self.assertFalse(d.get('rejected'), d)
        self.assertEqual(d['created'], 2)
        self.assertEqual(ARRecord.objects.filter(project=p, operation_month=1).count(), 2)

    # ── 合同 CRUD API（含 parties / projects 关联同步）─────────────────────────
    def _cpost(self, url, payload):
        return self.client.post(url, data=json.dumps(payload),
                                content_type='application/json', **self.auth())

    def _cput(self, url, payload):
        return self.client.put(url, data=json.dumps(payload),
                               content_type='application/json', **self.auth())

    def test_contract_api_create_with_links(self):
        c1 = Customer.objects.create(name='API客户甲')
        c2 = Customer.objects.create(name='API客户乙')
        p1 = self._proj('API项目A'); p2 = self._proj('API项目B')
        resp = self._cpost('/api/pk/ar/contracts', {
            'name': 'API合同', 'delivery_dept': self.dept, 'amount': '500000',
            'parties': [{'customer_id': c1.id, 'role': 'main', 'share': '70'},
                        {'customer_id': c2.id, 'role': 'sub', 'share': '30'}],
            'projects': [{'project_id': p1.id, 'is_primary': True},
                         {'project_id': p2.id, 'is_primary': False}],
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(len(d['parties']), 2)
        self.assertEqual(len(d['projects']), 2)
        ct = Contract.objects.get(pk=d['id'])
        self.assertEqual(ct.customers.count(), 2)
        self.assertEqual(ct.projects.count(), 2)

    def test_contract_api_update_replaces_parties(self):
        c1 = Customer.objects.create(name='U客户甲')
        c2 = Customer.objects.create(name='U客户乙')
        ct = Contract.objects.create(name='U合同', delivery_dept=self.dept)
        ContractParty.objects.create(contract=ct, customer=c1, role='main')
        resp = self._cput(f'/api/pk/ar/contracts/{ct.id}', {
            'parties': [{'customer_id': c2.id, 'role': 'main'}],
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        ct.refresh_from_db()
        self.assertEqual(list(ct.customers.values_list('name', flat=True)), ['U客户乙'])

    def test_contract_api_partial_update_keeps_links(self):
        c1 = Customer.objects.create(name='K客户')
        ct = Contract.objects.create(name='K合同', delivery_dept=self.dept)
        ContractParty.objects.create(contract=ct, customer=c1, role='main')
        # 不传 parties/projects → 关联不应被清空
        resp = self._cput(f'/api/pk/ar/contracts/{ct.id}', {'notes': '仅改备注'})
        self.assertEqual(resp.status_code, 200, resp.content)
        ct.refresh_from_db()
        self.assertEqual(ct.customers.count(), 1)
        self.assertEqual(ct.notes, '仅改备注')

    def test_contract_api_list_and_delete(self):
        ct = Contract.objects.create(name='L合同', delivery_dept=self.dept)
        Customer.objects.create(name='L客户')
        resp = self.client.get('/api/pk/ar/contracts', **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(any(x['name'] == 'L合同' for x in resp.json()['data']['items']))
        # delete
        resp2 = self.client.delete(f'/api/pk/ar/contracts/{ct.id}', **self.auth())
        self.assertEqual(resp2.status_code, 200, resp2.content)
        self.assertFalse(Contract.objects.filter(pk=ct.id).exists())

    def test_contract_no_auto_generated(self):
        ct = Contract.objects.create(name='自动编号合同', delivery_dept='运输事业部')
        self.assertTrue(ct.contract_no.startswith('P-YS-'), ct.contract_no)
        ct2 = Contract.objects.create(name='自动编号合同2', delivery_dept='运输事业部')
        # 同部门同日序号自增
        self.assertNotEqual(ct.contract_no, ct2.contract_no)
        # 显式指定则不覆盖
        ct3 = Contract.objects.create(name='手填编号', delivery_dept='运输事业部', contract_no='MY-001')
        self.assertEqual(ct3.contract_no, 'MY-001')

    def test_contract_no_auto_without_dept(self):
        ct = Contract.objects.create(name='无部门合同')
        self.assertTrue(ct.contract_no.startswith('P-'), ct.contract_no)
        self.assertNotIn('--', ct.contract_no)  # 无部门段不应出现空段

    def test_project_put_attaches_contracts_and_customer(self):
        cust = Customer.objects.create(name='挂靠客户')
        ct = Contract.objects.create(name='挂靠合同', delivery_dept=self.dept)
        p = self._proj('挂靠项目')
        resp = self._cput(f'/api/pk/ar/projects/{p.id}', {
            'customer_id': cust.id, 'contract_ids': [ct.id],
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['customer_id'], cust.id)
        self.assertEqual(len(d['contracts']), 1)
        self.assertEqual(d['contracts'][0]['contract_id'], ct.id)
        # GET 详情也带 contracts
        g = self.client.get(f'/api/pk/ar/projects/{p.id}', **self.auth()).json()['data']
        self.assertEqual(len(g['contracts']), 1)

    def test_project_put_clearing_contracts(self):
        ct = Contract.objects.create(name='待清合同', delivery_dept=self.dept)
        p = self._proj('待清项目')
        ContractProject.objects.create(contract=ct, project=p)
        resp = self._cput(f'/api/pk/ar/projects/{p.id}', {'contract_ids': []})
        self.assertEqual(resp.status_code, 200, resp.content)
        p.refresh_from_db()
        self.assertEqual(p.contracts.count(), 0)

    # ── 导出带回款日期/金额 + 合并年月筛选 ────────────────────────────────────
    def test_export_includes_payment_date_amount(self):
        from openpyxl import load_workbook
        p = self._proj('导出回款项目')
        r = ARRecord.objects.create(project=p, operation_year=2026, operation_month=3,
                                    estimated_amount=Decimal('100000'))
        ARPayment.objects.create(ar_record=r, payment_no=1, amount=Decimal('30000'),
                                 payment_date=date(2026, 3, 20))
        ARPayment.objects.create(ar_record=r, payment_no=2, amount=Decimal('20000'),
                                 payment_date=date(2026, 4, 10))
        resp = self.client.get('/api/pk/ar/records/export', **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb.active
        headers = [c.value for c in ws[1]]
        self.assertIn('回款日期', headers)
        self.assertIn('回款金额', headers)
        self.assertIn('已回款合计', headers)
        # 找到数据行，校验两笔回款并列 + 合计
        di, dl = headers.index('回款日期'), headers.index('回款金额')
        ti = headers.index('已回款合计')
        row = [c.value for c in ws[2]]
        self.assertIn('2026-03-20', str(row[di]))
        self.assertIn('2026-04-10', str(row[di]))
        self.assertIn('30000', str(row[dl]))
        self.assertEqual(float(row[ti]), 50000.0)

    def test_combined_year_month_condition(self):
        p = self._proj('年月筛选项目')
        ARRecord.objects.create(project=p, operation_year=2026, operation_month=1,
                                estimated_amount=Decimal('1000'))
        ARRecord.objects.create(project=p, operation_year=2026, operation_month=2,
                                estimated_amount=Decimal('2000'))
        conds = json.dumps([{'t': 'dim', 'field': 'operation_ym', 'value': '2026-01'}])
        resp = self.client.get('/api/pk/ar/records', {'conditions': conds, 'match': 'all'},
                               **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['total'], 1)
        self.assertEqual(d['items'][0]['operation_month'], 1)
        # summary 合计也只统计该月
        self.assertEqual(d['summary']['count'], 1)
        self.assertAlmostEqual(float(d['summary']['estimated']), 1000.0, places=2)

    def test_operation_ym_range_and_exclude(self):
        """运作年月支持区间(start~end)与含/不含反选。"""
        p = self._proj('年月区间项目')
        for ym in [(2025, 12), (2026, 1), (2026, 3), (2026, 6)]:
            ARRecord.objects.create(project=p, operation_year=ym[0], operation_month=ym[1],
                                    estimated_amount=Decimal('100'))

        def months(cond):
            conds = json.dumps([cond])
            resp = self.client.get('/api/pk/ar/records', {'conditions': conds}, **self.auth())
            self.assertEqual(resp.status_code, 200, resp.content)
            return sorted((r['operation_year'], r['operation_month'])
                          for r in resp.json()['data']['items'])

        # 区间 2026-01 ~ 2026-03 → 含 1月、3月
        self.assertEqual(months({'t': 'dim', 'field': 'operation_ym',
                                  'value': '2026-01', 'end': '2026-03'}),
                         [(2026, 1), (2026, 3)])
        # 跨年区间 2025-12 ~ 2026-01
        self.assertEqual(months({'t': 'dim', 'field': 'operation_ym',
                                  'value': '2025-12', 'end': '2026-01'}),
                         [(2025, 12), (2026, 1)])
        # 不含 2026-01 ~ 2026-03 → 排除区间内，留 2025-12 与 2026-06
        self.assertEqual(months({'t': 'dim', 'field': 'operation_ym',
                                  'value': '2026-01', 'end': '2026-03', 'exclude': True}),
                         [(2025, 12), (2026, 6)])
        # 仅 start（无 end）退化为单月
        self.assertEqual(months({'t': 'dim', 'field': 'operation_ym', 'value': '2026-06'}),
                         [(2026, 6)])

    def test_condition_group_parentheses(self):
        """条件组（括号）：(A 且 B) 或 C 复合筛选。"""
        p = self._proj('括号筛选项目')
        # a: 2026-01 预估 100；b: 2026-01 预估 500；c: 2026-09 预估 500
        a = ARRecord.objects.create(project=p, operation_year=2026, operation_month=1,
                                    estimated_amount=Decimal('100'))
        b = ARRecord.objects.create(project=p, operation_year=2026, operation_month=1,
                                    estimated_amount=Decimal('500'))
        c = ARRecord.objects.create(project=p, operation_year=2026, operation_month=9,
                                    estimated_amount=Decimal('500'))

        # (运作=2026-01 且 预估>200) 或 (运作=2026-09)
        conds = json.dumps([
            {'t': 'group', 'match': 'all', 'conditions': [
                {'t': 'dim', 'field': 'operation_ym', 'value': '2026-01'},
                {'t': 'amt', 'field': 'estimated_amount', 'op': 'gt', 'value': 200},
            ]},
            {'t': 'dim', 'field': 'operation_ym', 'value': '2026-09'},
        ])
        resp = self.client.get('/api/pk/ar/records', {'conditions': conds, 'match': 'any'},
                               **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        got = {r['id'] for r in resp.json()['data']['items']}
        self.assertEqual(got, {b.id, c.id})   # a 被组内 预估>200 排除
        self.assertNotIn(a.id, got)

    def test_same_month_same_project_multiple_rows_kept_distinct(self):
        """同项目同年同月多条不同金额：各自独立入库，绝不合并、不取第一条覆盖。"""
        p = self._proj('同月多笔项目')
        HEAD = ['项目编号', '项目简称*', '客户名称', '运作年*', '运作月*', '预估上账金额',
                '实际开票金额', '税额(差额模式手填)', '开票日期', '账实差额调整',
                '回款金额', '回款时间', '备注']
        d = self._upload_records(HEAD, [
            ['', '同月多笔项目', '', 2026, 4, 59545.44, '', '', '', '', '', '', '第一笔'],
            ['', '同月多笔项目', '', 2026, 4, 251264.44, '', '', '', '', '', '', '第二笔'],
            ['', '同月多笔项目', '', 2026, 4, 107377.24, '', '', '', '', '', '', '第三笔'],
        ]).json()['data']
        self.assertFalse(d.get('rejected'), d)
        self.assertEqual(d['created'], 3, d)
        recs = ARRecord.objects.filter(project=p, operation_year=2026, operation_month=4)
        self.assertEqual(recs.count(), 3)
        amounts = sorted(float(r.estimated_amount) for r in recs)
        self.assertEqual(amounts, [59545.44, 107377.24, 251264.44])   # 三个金额都在，未被覆盖
        total = sum(float(r.estimated_amount) for r in recs)
        self.assertAlmostEqual(total, 418187.12, places=2)
