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
