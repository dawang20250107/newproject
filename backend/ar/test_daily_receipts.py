"""日常收款：CRUD + 计入资金池 + 计入现金流。"""
import datetime
import json
from decimal import Decimal

from django.test import Client, TestCase

from paikuan.models import PaikuanUser
from paikuan.views import make_token, _invalidate_perm_cache
from ar.models import ARProject, CashPoolConfig, DailyReceipt


class DailyReceiptTests(TestCase):
    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '劳务事业部'
        self.other = '运输事业部'
        self.admin = self._user('13900001001', 'super_admin', [self.dept, self.other])
        self.op = self._user('13900001002', 'operator', [self.dept])

    def tearDown(self):
        _invalidate_perm_cache()

    def _user(self, phone, role, depts):
        u = PaikuanUser(phone=phone, name=role, role=role, job_title='finance_director',
                        departments=depts, is_active=True, is_approved=True)
        u.set_password('Test123456'); u.save()
        return u

    def _auth(self, u):
        return {'HTTP_AUTHORIZATION': f'Bearer {make_token(u)}'}

    def _post(self, url, body, u):
        return self.client.post(url, data=json.dumps(body), content_type='application/json', **self._auth(u))

    def test_create_list_and_totals(self):
        proj = ARProject.objects.create(customer_name='C', short_name='P1', delivery_dept=self.dept,
                                        sub_dept='S', business_mode='M', customer_level='A级')
        r = self._post('/api/pk/ar/daily-receipts', {
            'delivery_dept': self.dept, 'receipt_date': '2026-06-10', 'amount': '1200.00',
            'source': '项目收款', 'project_id': proj.id, 'method': '微信', 'payer': '甲方'}, self.admin)
        self.assertEqual(r.status_code, 200, r.content)
        self._post('/api/pk/ar/daily-receipts', {
            'delivery_dept': self.dept, 'receipt_date': '2026-06-11', 'amount': '800',
            'source': '预付退款', 'method': '银行转账'}, self.admin)
        g = self.client.get('/api/pk/ar/daily-receipts', **self._auth(self.admin)).json()['data']
        self.assertEqual(g['count'], 2)
        self.assertEqual(Decimal(g['total']), Decimal('2000'))
        self.assertEqual(Decimal(g['by_method']['微信']), Decimal('1200'))

    def test_validation(self):
        # 金额<=0、日期未来、无效部门都应拒绝
        self.assertEqual(self._post('/api/pk/ar/daily-receipts', {
            'delivery_dept': self.dept, 'receipt_date': '2026-06-10', 'amount': '0',
            'source': '项目收款'}, self.admin).status_code, 400)
        future = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        self.assertEqual(self._post('/api/pk/ar/daily-receipts', {
            'delivery_dept': self.dept, 'receipt_date': future, 'amount': '10',
            'source': 'x'}, self.admin).status_code, 400)

    def test_operator_scoped_to_own_dept(self):
        r = self._post('/api/pk/ar/daily-receipts', {
            'delivery_dept': self.other, 'receipt_date': '2026-06-10', 'amount': '10',
            'source': 'x'}, self.op)   # op 只在 劳务，不能录 运输
        self.assertEqual(r.status_code, 403, r.content)

    def test_counts_into_cash_pool(self):
        from ar.views.pool import _pool_balance
        cfg = CashPoolConfig.objects.create(delivery_dept=self.dept,
            initial_date=datetime.date(2026, 6, 1), initial_amount=Decimal('1000'))
        today = datetime.date(2026, 6, 30)
        base = _pool_balance(self.dept, cfg, today)
        DailyReceipt.objects.create(delivery_dept=self.dept, receipt_date=datetime.date(2026, 6, 15),
                                    amount=Decimal('500'), source='项目收款', method='现金')
        after = _pool_balance(self.dept, cfg, today)
        self.assertEqual(after - base, Decimal('500'))   # 日常收款增加资金池余额

    def test_bulk_delete(self):
        ids = []
        for i in range(3):
            r = self._post('/api/pk/ar/daily-receipts', {
                'delivery_dept': self.dept, 'receipt_date': '2026-06-10', 'amount': '100',
                'source': '项目收款'}, self.admin)
            ids.append(r.json()['data']['id'])
        r = self._post('/api/pk/ar/daily-receipts/bulk-delete', {'ids': ids[:2]}, self.admin)
        self.assertEqual(r.json()['data']['deleted'], 2)
        self.assertEqual(DailyReceipt.objects.count(), 1)

    def test_counts_into_cashflow(self):
        DailyReceipt.objects.create(delivery_dept=self.dept, receipt_date=datetime.date(2026, 6, 15),
                                    amount=Decimal('700'), source='预付退款', method='银行转账')
        r = self.client.get('/api/pk/ar/cashflow?start_date=2026-06-01&end_date=2026-06-30',
                            **self._auth(self.admin)).json()['data']
        idx = r['months'].index('2026-06')
        self.assertEqual(r['totals']['daily_receipts'][idx], 700.0)
        self.assertGreaterEqual(r['totals']['inflow'][idx], 700.0)   # 计入现金流入
