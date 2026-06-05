import json
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from paikuan.models import JobPermission, PaikuanUser, Payment
from paikuan.views import DEPARTMENTS, default_job_config, make_token, _invalidate_perm_cache


class PaymentPermissionRegressionTests(TestCase):
    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = DEPARTMENTS[0]
        self.user = PaikuanUser(
            phone='13900000001',
            name='Cashier User',
            role='operator',
            job_title='cashier',
            departments=[self.dept],
            is_active=True,
            is_approved=True,
        )
        self.user.set_password('Test123456')
        self.user.save()
        self.token = make_token(self.user)

    def tearDown(self):
        _invalidate_perm_cache()

    def auth(self, token=None):
        return {'HTTP_AUTHORIZATION': f'Bearer {token or self.token}'}

    def put_payment(self, payment_id, payload, token=None):
        return self.client.put(
            f'/api/pk/payments/{payment_id}',
            data=json.dumps(payload),
            content_type='application/json',
            **self.auth(token),
        )

    def create_payment(self, total='1000.00'):
        return Payment.objects.create(
            created_by=self.user,
            department=self.dept,
            approval_number='',
            project_desc='Regression project',
            payee='Regression payee',
            total_amount=Decimal(total),
            planned_date=date(2026, 6, 1),
            pay1_amount=Decimal('0'),
            pay2_amount=Decimal('0'),
            pay3_amount=Decimal('0'),
            notes='',
        )

    def test_prepaid_balance_lookup_for_payment(self):
        """排款页按项目编号查预付余额：匹配项目返回未核销合计，未匹配返回空。"""
        from ar.models import ARProject, AdvanceRecord
        proj = ARProject.objects.create(
            contract_name='C', short_name='预付项目', delivery_dept=self.dept,
            sales_contact='S', project_manager='M', project_no='GYL-TEST-0001')
        AdvanceRecord.objects.create(
            direction='预付', project=proj, delivery_dept=self.dept, counterparty='供应商A',
            occur_year=2026, occur_month=3, occur_date=date(2026, 3, 1),
            advance_amount=Decimal('80000'))
        resp = self.client.get('/api/pk/payments/prepaid-balance',
                               {'project_no': 'GYL-TEST-0001'}, **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertTrue(d['matched'])
        self.assertEqual(d['count'], 1)
        self.assertEqual(d['total_balance'], '80000.00')
        # 未匹配项目编号 → 空
        resp2 = self.client.get('/api/pk/payments/prepaid-balance',
                                {'project_no': 'NOPE'}, **self.auth())
        self.assertFalse(resp2.json()['data']['matched'])

    def test_payment_create_persists_project_no(self):
        from paikuan.views import default_job_config
        JobPermission.objects.update_or_create(
            job_title='cashier', defaults={'config': default_job_config('cashier')})
        _invalidate_perm_cache()
        resp = self.client.post(
            '/api/pk/payments',
            data=json.dumps({'department': self.dept, 'project_no': 'GYL-TEST-0002',
                             'project_desc': 'D', 'payee': 'P', 'total_amount': '5000',
                             'planned_date': '2026-06-01'}),
            content_type='application/json', **self.auth())
        if resp.status_code == 200:
            self.assertEqual(resp.json()['data']['project_no'], 'GYL-TEST-0002')

    def test_stale_token_rejected_after_user_deactivated(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        resp = self.client.get('/api/pk/me', **self.auth())

        self.assertEqual(resp.status_code, 401)

    def test_stale_token_departments_are_ignored(self):
        payment = self.create_payment()
        stale_token = make_token(self.user)
        self.user.departments = []
        self.user.save(update_fields=['departments'])

        resp = self.put_payment(payment.id, {'pay1_date': '2026-06-02', 'pay1_amount': '100.00'}, stale_token)

        self.assertEqual(resp.status_code, 403)

    def test_non_editable_total_cannot_bypass_overpay_validation(self):
        payment = self.create_payment(total='1000.00')

        resp = self.put_payment(
            payment.id,
            {
                'total_amount': '5000.00',
                'pay1_date': '2026-06-02',
                'pay1_amount': '2000.00',
            },
        )

        self.assertEqual(resp.status_code, 400)
        payment.refresh_from_db()
        self.assertEqual(payment.pay1_amount, Decimal('0.00'))

    def test_blank_non_editable_fields_are_ignored_on_partial_edit(self):
        payment = self.create_payment(total='1000.00')

        resp = self.put_payment(
            payment.id,
            {
                'department': '',
                'approval_number': 'not-21-digits',
                'project_desc': '',
                'payee': '',
                'total_amount': '',
                'planned_date': '',
                'pay1_date': '2026-06-03',
                'pay1_amount': '100.00',
            },
        )

        self.assertEqual(resp.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.project_desc, 'Regression project')
        self.assertEqual(payment.payee, 'Regression payee')
        self.assertEqual(payment.total_amount, Decimal('1000.00'))
        self.assertEqual(payment.pay1_amount, Decimal('100.00'))

    def test_payments_page_permission_blocks_related_endpoints(self):
        cfg = default_job_config('cashier')
        cfg['pages']['payments'] = False
        JobPermission.objects.create(job_title='cashier', config=cfg)
        _invalidate_perm_cache('cashier')

        checks = [
            self.client.get('/api/pk/payments', **self.auth()),
            self.client.get('/api/pk/payments/export', **self.auth()),
            self.client.get('/api/pk/payments/template', **self.auth()),
            self.client.get('/api/pk/departments', **self.auth()),
            self.client.post('/api/pk/payments/import', **self.auth()),
        ]

        self.assertTrue(all(resp.status_code == 403 for resp in checks))


class ApprovalImportTests(TestCase):
    """审批记录导入：表头健壮匹配（兼容导出文件/无星号）、缺列明确报错、跳过原因返回。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = DEPARTMENTS[0]
        u = PaikuanUser(phone='13900000200', name='Admin', role='super_admin',
                        job_title='finance_director', departments=[self.dept],
                        is_active=True, is_approved=True)
        u.set_password('Test123456'); u.save()
        self.token = make_token(u)

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def _xlsx(self, headers, rows):
        import io
        from openpyxl import Workbook
        from django.core.files.uploadedfile import SimpleUploadedFile
        wb = Workbook(); ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        return SimpleUploadedFile('approvals.xlsx', buf.read(),
                                  content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    def test_import_accepts_export_style_headers_without_asterisk(self):
        # 导出文件表头不带 * —— 之前会整表跳过；现在应能正常导入
        headers = ['申请人', '所属事业部', '审批编号', '摘要', '申请金额', '收款主体', '审批状态']
        rows = [['张三', self.dept, '1' * 21, '摘要A', 12000, '某供应商', '待审批']]
        resp = self.client.post('/api/pk/approvals/import',
                                {'file': self._xlsx(headers, rows)}, **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['created'], 1, d)
        self.assertEqual(d['skipped'], 0, d)

    def test_import_missing_required_header_errors_clearly(self):
        headers = ['姓名', '事业部X', '金额X']  # 无 申请人/申请金额
        resp = self.client.post('/api/pk/approvals/import',
                                {'file': self._xlsx(headers, [['x', 'y', 1]])}, **self.auth())
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('表头', resp.json().get('error', ''))

    def test_import_returns_skip_reasons(self):
        headers = ['申请人*', '所属事业部*', '审批编号*', '摘要', '申请金额*', '收款主体', '审批状态*']
        rows = [
            ['李四', self.dept, '2' * 21, '', 5000, '', '待审批'],       # ok
            ['王五', self.dept, '123', '', 6000, '', '待审批'],          # 审批编号非21位
            ['赵六', '不存在事业部', '3' * 21, '', 7000, '', '待审批'],   # 部门无效
            ['示例张三', self.dept, '4' * 21, '示例摘要', 9, '', '待审批'],  # 示例行静默跳过
        ]
        resp = self.client.post('/api/pk/approvals/import',
                                {'file': self._xlsx(headers, rows)}, **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        self.assertEqual(d['created'], 1, d)
        self.assertEqual(d['skipped'], 2, d)          # 示例行不计入跳过
        self.assertEqual(len(d['errors']), 2, d)


class StatsCarryoverTests(TestCase):
    """月度统计：前期未付的排款结转到本期展示。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = DEPARTMENTS[0]
        u = PaikuanUser(phone='13900000300', name='Admin', role='super_admin',
                        job_title='finance_director', departments=[self.dept],
                        is_active=True, is_approved=True)
        u.set_password('Test123456'); u.save()
        self.user = u
        self.token = make_token(u)

    def tearDown(self):
        _invalidate_perm_cache()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def _pay(self, planned, total, pay1='0', dept=None):
        return Payment.objects.create(
            created_by=self.user, department=dept or self.dept,
            approval_number='', project_desc='P', payee='Payee',
            total_amount=Decimal(total), planned_date=planned,
            pay1_amount=Decimal(pay1), pay2_amount=Decimal('0'),
            pay3_amount=Decimal('0'), notes='')

    def test_prior_unpaid_carries_into_current_period(self):
        # 本期(2026-06)：计划 1000，已付 400
        self._pay(date(2026, 6, 10), '1000', pay1='400')
        # 前期(2026-05)：计划 800，已付 300 → 剩余 500 应结转
        self._pay(date(2026, 5, 10), '800', pay1='300')
        # 前期(2026-04)：计划 600，已付清 → 不结转
        self._pay(date(2026, 4, 10), '600', pay1='600')
        resp = self.client.get('/api/pk/stats',
                               {'year': 2026, 'month': 6}, **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        d = resp.json()['data']
        # 本期口径不变：仅含 6 月
        self.assertEqual(Decimal(d['total_amount']), Decimal('1000'))
        self.assertEqual(Decimal(d['total_remaining']), Decimal('600'))
        # 前期结转：仅 5 月那笔剩余 500（4 月已付清排除）
        self.assertEqual(Decimal(d['carryover_remaining']), Decimal('500'))
        self.assertEqual(d['carryover_count'], 1)
        # 累计应付未付 = 600 + 500
        self.assertEqual(Decimal(d['total_outstanding']), Decimal('1100'))
        # 部门行带结转
        row = next(r for r in d['by_dept'] if r['dept'] == self.dept)
        self.assertEqual(Decimal(row['carry']), Decimal('500'))
        self.assertEqual(Decimal(row['outstanding']), Decimal('1100'))

    def test_dept_with_only_carryover_appears(self):
        # 某部门本期无计划，但有前期未付 → 仍应出现在 by_dept
        other = DEPARTMENTS[1]
        self._pay(date(2026, 5, 1), '700', pay1='0', dept=other)
        resp = self.client.get('/api/pk/stats',
                               {'year': 2026, 'month': 6}, **self.auth())
        d = resp.json()['data']
        row = next(r for r in d['by_dept'] if r['dept'] == other)
        self.assertEqual(Decimal(row['total']), Decimal('0'))
        self.assertEqual(Decimal(row['carry']), Decimal('700'))
        self.assertEqual(row['carry_count'], 1)


class PaymentApplicantTests(TestCase):
    """排款记录的申请人字段：创建/编辑、一键排款带出、模板与导出含申请人列。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = DEPARTMENTS[0]
        u = PaikuanUser(phone='13900000400', name='Admin', role='super_admin',
                        job_title='finance_director', departments=[self.dept],
                        is_active=True, is_approved=True)
        u.set_password('Test123456'); u.save()
        self.user = u
        self.token = make_token(u)

    def tearDown(self):
        _invalidate_perm_cache()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def test_create_payment_persists_applicant(self):
        payload = {
            'department': self.dept, 'applicant': '张三',
            'project_desc': '工程款', 'payee': '某公司',
            'total_amount': '1000', 'planned_date': '2026-06-01',
        }
        resp = self.client.post('/api/pk/payments', data=json.dumps(payload),
                                content_type='application/json', **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['applicant'], '张三')
        self.assertEqual(Payment.objects.get(id=resp.json()['data']['id']).applicant, '张三')

    def test_schedule_carries_applicant_from_approval(self):
        from paikuan.models import ApprovalRecord
        rec = ApprovalRecord.objects.create(
            applicant='李四', department=self.dept, approval_number='1' * 21,
            summary='付款摘要', amount=Decimal('5000'), payee='供应商A',
            status='approved')
        resp = self.client.post(f'/api/pk/approvals/{rec.id}/schedule',
                                data=json.dumps({'planned_date': '2026-06-10',
                                                 'total_amount': '5000'}),
                                content_type='application/json', **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['data']['payment']['applicant'], '李四')

    def test_template_and_export_include_applicant_header(self):
        from openpyxl import load_workbook
        import io
        # 模板
        tpl = self.client.get('/api/pk/payments/template', **self.auth())
        self.assertEqual(tpl.status_code, 200, tpl.content)
        ws = load_workbook(io.BytesIO(tpl.content)).active
        headers = [c.value for c in ws[1]]
        self.assertIn('申请人', headers)
        # 导出
        Payment.objects.create(created_by=self.user, department=self.dept,
                               applicant='王五', approval_number='', project_desc='P',
                               payee='X', total_amount=Decimal('100'),
                               planned_date=date(2026, 6, 1))
        exp = self.client.get('/api/pk/payments/export', **self.auth())
        self.assertEqual(exp.status_code, 200, exp.content)
        ws2 = load_workbook(io.BytesIO(exp.content)).active
        headers2 = [c.value for c in ws2[1]]
        self.assertIn('申请人', headers2)
        col = headers2.index('申请人')
        self.assertEqual(ws2[2][col].value, '王五')
