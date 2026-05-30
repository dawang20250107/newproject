import io
import json
from datetime import date
from decimal import Decimal

import openpyxl
from django.test import Client, TestCase

from ar.models import ARPayment, ARProject, ARRecord, CollectionBudget, PaymentBudget
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

    def create_project(self, dept=None):
        return ARProject.objects.create(
            contract_name='Contract A',
            short_name='Project A',
            delivery_dept=dept or self.dept,
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
            'contract_name': 'Contract B',
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
        cfg['ar_view']['p_contract_name'] = False
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

        # date range + pay_include_unpaid=1 → OR: June-paid OR no-payments-ever
        combined = ids({'pay_start': '2026-06-01', 'pay_end': '2026-06-30', 'pay_include_unpaid': '1'})
        self.assertIn(paid.id, combined)
        self.assertIn(unpaid.id, combined)

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

    def test_records_search_matches_project_manager(self):
        admin = self.make_user('13900000066', 'finance_director', role='super_admin')
        project = self.create_project()  # project_manager 'PM A'
        rec = self.create_record(project)

        resp = self.client.get('/api/pk/ar/records', {'q': 'PM A'}, **self.auth(admin))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(rec.id, {r['id'] for r in resp.json()['data']['items']})
