"""内部往来核销（事业部间往来，不涉及资金流动）全链路测试。

口径：比照「预收抵扣」——冲减应收未收，但不计现金/资金池/现金流，
仍计入应收口径的回款达成；支持单次/多次；可编辑、可删除（恢复未收）。
"""
import json
from datetime import date
from decimal import Decimal

from django.test import Client, TestCase

from ar.models import ARPayment, ARProject, ARRecord
from paikuan.models import PaikuanUser
from paikuan.views import make_token, _invalidate_perm_cache


class InternalSettlementTests(TestCase):
    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '运输事业部'
        self.cp_dept = '供应链事业部'   # 往来部门（对方事业部）
        admin = PaikuanUser(phone='13900009100', name='IntAdmin', role='super_admin',
                            job_title='finance_director', departments=[self.dept],
                            is_active=True, is_approved=True)
        admin.set_password('Test123456'); admin.save()
        self.token = make_token(admin)
        self.proj = ARProject.objects.create(
            customer_name='内部客户', short_name='内部项目', delivery_dept=self.dept,
            sales_contact='S', project_manager='M', project_no='INT-0001')
        self.rec = ARRecord.objects.create(project=self.proj, operation_date=date(2026, 3, 1),
                                           estimated_amount=Decimal('1000'))

    def tearDown(self):
        _invalidate_perm_cache()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def _post_pay(self, payload):
        return self.client.post(f'/api/pk/ar/records/{self.rec.id}/payments',
                                data=json.dumps(payload), content_type='application/json',
                                **self.auth())

    def test_create_internal_settlement_reduces_outstanding(self):
        r = self._post_pay({'amount': 300, 'payment_date': '2026-03-10',
                            'source': '内部往来', 'counterparty_dept': self.cp_dept})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        self.assertEqual(d['source'], '内部往来')
        self.assertEqual(d['counterparty_dept'], self.cp_dept)
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.outstanding_amount, Decimal('700.00'))  # 1000 - 300

    def test_multiple_internal_settlements(self):
        self._post_pay({'amount': 300, 'payment_date': '2026-03-10',
                        'source': '内部往来', 'counterparty_dept': self.cp_dept})
        self._post_pay({'amount': 200, 'payment_date': '2026-03-20',
                        'source': '内部往来', 'counterparty_dept': '自营事业部'})
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.outstanding_amount, Decimal('500.00'))  # 1000 - 500
        self.assertEqual(self.rec.payments.filter(source='内部往来').count(), 2)

    def test_internal_requires_valid_counterparty(self):
        r1 = self._post_pay({'amount': 100, 'payment_date': '2026-03-10', 'source': '内部往来'})
        self.assertEqual(r1.status_code, 400, r1.content)
        r2 = self._post_pay({'amount': 100, 'payment_date': '2026-03-10',
                             'source': '内部往来', 'counterparty_dept': '不存在部'})
        self.assertEqual(r2.status_code, 400, r2.content)
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.outstanding_amount, Decimal('1000.00'))  # 未变

    def test_cannot_manually_create_prepaid_offset(self):
        r = self._post_pay({'amount': 100, 'payment_date': '2026-03-10', 'source': '预收抵扣'})
        self.assertEqual(r.status_code, 400, r.content)

    def test_internal_excluded_from_cash_but_reduces_outstanding(self):
        self._post_pay({'amount': 200, 'payment_date': '2026-03-12', 'source': '回款'})
        self._post_pay({'amount': 300, 'payment_date': '2026-03-12',
                        'source': '内部往来', 'counterparty_dept': self.cp_dept})
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.outstanding_amount, Decimal('500.00'))  # 两者都冲减未收
        resp = self.client.get('/api/pk/ar/cashflow',
                               {'start_date': '2026-03-01', 'end_date': '2026-03-31',
                                'depts': self.dept}, **self.auth())
        t = resp.json()['data']['totals']
        self.assertEqual(t['collected'][0], 200.0)   # 内部往来不计现金回款

    def test_internal_settlement_editable_and_deletable(self):
        r = self._post_pay({'amount': 300, 'payment_date': '2026-03-10',
                            'source': '内部往来', 'counterparty_dept': self.cp_dept})
        pid = r.json()['data']['id']
        e = self.client.put(f'/api/pk/ar/records/{self.rec.id}/payments/{pid}',
                            data=json.dumps({'amount': 400, 'counterparty_dept': '自营事业部'}),
                            content_type='application/json', **self.auth())
        self.assertEqual(e.status_code, 200, e.content)
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.outstanding_amount, Decimal('600.00'))  # 1000 - 400
        self.assertEqual(ARPayment.objects.get(pk=pid).counterparty_dept, '自营事业部')
        d = self.client.delete(f'/api/pk/ar/records/{self.rec.id}/payments/{pid}',
                               **self.auth())
        self.assertEqual(d.status_code, 200, d.content)
        self.rec.refresh_from_db()
        self.assertEqual(self.rec.outstanding_amount, Decimal('1000.00'))

    def test_internal_shows_in_payment_ledger_with_source(self):
        self._post_pay({'amount': 300, 'payment_date': '2026-03-10',
                        'source': '内部往来', 'counterparty_dept': self.cp_dept})
        resp = self.client.get('/api/pk/ar/records/payments',
                               {'source': '内部往来'}, **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        items = resp.json()['data']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['source'], '内部往来')
        self.assertEqual(items[0]['counterparty_dept'], self.cp_dept)


class ARListIncludesAdjustmentsTests(TestCase):
    """应收列表行需带出差额调整明细，供编辑弹窗直接展示/删除。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '运输事业部'
        admin = PaikuanUser(phone='13900009200', name='AdjAdmin', role='super_admin',
                            job_title='finance_director', departments=[self.dept],
                            is_active=True, is_approved=True)
        admin.set_password('Test123456'); admin.save()
        self.token = make_token(admin)
        self.proj = ARProject.objects.create(
            customer_name='调整客户', short_name='调整项目', delivery_dept=self.dept,
            sales_contact='S', project_manager='M', project_no='ADJ-0001')
        self.rec = ARRecord.objects.create(project=self.proj, operation_date=date(2026, 3, 1),
                                           estimated_amount=Decimal('1000'))

    def tearDown(self):
        _invalidate_perm_cache()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def test_list_row_carries_adjustments(self):
        # 追加两笔差额调整
        for amt, reason in [(50, '运费差'), (-20, '客户扣款')]:
            r = self.client.post(f'/api/pk/ar/records/{self.rec.id}/adjustments',
                                 data=json.dumps({'amount': amt, 'reason': reason}),
                                 content_type='application/json', **self.auth())
            self.assertEqual(r.status_code, 200, r.content)
        # 列表行应带出 adjustments（编辑弹窗据此渲染删除）；前端列表带 include_payments=1
        resp = self.client.get('/api/pk/ar/records',
                               {'q': '调整项目', 'include_payments': 1}, **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        row = next(it for it in resp.json()['data']['items'] if it['id'] == self.rec.id)
        self.assertIn('adjustments', row)
        self.assertEqual(len(row['adjustments']), 2)
        reasons = {a['reason'] for a in row['adjustments']}
        self.assertEqual(reasons, {'运费差', '客户扣款'})
