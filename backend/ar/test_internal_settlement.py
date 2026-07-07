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


class CollectionMethodTests(TestCase):
    """应收回款方式（现金/微信/银行转账/承兑汇票）+ 可选账户：录入/回显/校验/默认/
    非回款留空/导出列/按方式筛选/现金流口径中立/历史迁移映射。"""

    def setUp(self):
        _invalidate_perm_cache()
        self.client = Client()
        self.dept = '运输事业部'
        self.cp_dept = '供应链事业部'
        admin = PaikuanUser(phone='13900009300', name='MethodAdmin', role='super_admin',
                            job_title='finance_director', departments=[self.dept],
                            is_active=True, is_approved=True)
        admin.set_password('Test123456'); admin.save()
        self.token = make_token(admin)
        self.proj = ARProject.objects.create(
            customer_name='方式客户', short_name='方式项目', delivery_dept=self.dept,
            sales_contact='S', project_manager='M', project_no='PM-0001')
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

    def test_method_persist_and_echo(self):
        r = self._post_pay({'amount': 200, 'payment_date': '2026-03-10',
                            'source': '回款', 'method': '微信', 'account': '微信-结算001'})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        self.assertEqual(d['method'], '微信')
        self.assertEqual(d['account'], '微信-结算001')
        pay = ARPayment.objects.get(pk=d['id'])
        self.assertEqual(pay.method, '微信')
        self.assertEqual(pay.account, '微信-结算001')
        # 台账回读一致
        item = self.client.get('/api/pk/ar/records/payments', {'method': '微信'},
                               **self.auth()).json()['data']['items'][0]
        self.assertEqual(item['method'], '微信')
        self.assertEqual(item['account'], '微信-结算001')

    def test_method_defaults_bank_transfer(self):
        d = self._post_pay({'amount': 100, 'payment_date': '2026-03-10',
                            'source': '回款'}).json()['data']
        self.assertEqual(d['method'], '银行转账')     # API 默认
        # 对比：ORM 直接建的回款方式为空（模型默认 ''，非 API 默认）
        p = ARPayment.objects.create(ar_record=self.rec, payment_no=99,
                                     amount=Decimal('1'), payment_date=date(2026, 3, 1))
        self.assertEqual(p.method, '')

    def test_method_must_be_one_of_four(self):
        r = self._post_pay({'amount': 100, 'payment_date': '2026-03-10',
                            'source': '回款', 'method': '支付宝'})
        self.assertEqual(r.status_code, 400, r.content)
        # PUT 改成非法方式 → 400
        pid = self._post_pay({'amount': 100, 'payment_date': '2026-03-10',
                             'source': '回款', 'method': '现金'}).json()['data']['id']
        e = self.client.put(f'/api/pk/ar/records/{self.rec.id}/payments/{pid}',
                            data=json.dumps({'method': '比特币'}),
                            content_type='application/json', **self.auth())
        self.assertEqual(e.status_code, 400, e.content)

    def test_non_collection_sources_have_empty_method(self):
        # 内部往来：即便客户端硬塞 method/account，也强制留空
        d = self._post_pay({'amount': 300, 'payment_date': '2026-03-10', 'source': '内部往来',
                            'counterparty_dept': self.cp_dept,
                            'method': '现金', 'account': 'X'}).json()['data']
        self.assertEqual(d['method'], '')
        self.assertEqual(d['account'], '')
        pay = ARPayment.objects.get(pk=d['id'])
        self.assertEqual(pay.method, '')
        # PUT 给内部往来塞 method 被忽略（guard: 仅 source=回款 生效）
        e = self.client.put(f'/api/pk/ar/records/{self.rec.id}/payments/{pay.id}',
                            data=json.dumps({'method': '微信'}),
                            content_type='application/json', **self.auth())
        self.assertEqual(e.status_code, 200, e.content)
        pay.refresh_from_db()
        self.assertEqual(pay.method, '')

    def test_model_guard_clears_method_when_source_not_collection(self):
        # 绕过视图直接 ORM 写：save() 兜底清空非回款来源的方式/账户
        p = ARPayment(ar_record=self.rec, payment_no=50, amount=Decimal('10'),
                      payment_date=date(2026, 3, 1), source='内部往来',
                      counterparty_dept=self.cp_dept, method='现金', account='脏数据')
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.method, '')
        self.assertEqual(p.account, '')

    def test_cashflow_neutral_to_method(self):
        # 承兑汇票与银行转账都属 source='回款'，同计入现金回款（method 不影响现金口径）
        self._post_pay({'amount': 200, 'payment_date': '2026-03-12',
                        'source': '回款', 'method': '承兑汇票'})
        self._post_pay({'amount': 300, 'payment_date': '2026-03-12',
                        'source': '回款', 'method': '银行转账'})
        resp = self.client.get('/api/pk/ar/cashflow',
                               {'start_date': '2026-03-01', 'end_date': '2026-03-31',
                                'depts': self.dept}, **self.auth())
        t = resp.json()['data']['totals']
        self.assertEqual(t['collected'][0], 500.0)   # 承兑也计入

    def test_acceptance_draft_excluded_from_pool_but_in_cashflow(self):
        """承兑汇票口径：不算「可动用现金」→ 资金池账面余额排除；但仍是已实现现金流入
        → 现金流分析照常计入。"""
        from django.utils import timezone
        from ar.models import CashPoolConfig
        from ar.views.pool import _pool_balance
        cfg = CashPoolConfig.objects.create(
            delivery_dept=self.dept, initial_date=date(2026, 3, 1),
            initial_amount=Decimal('1000'))
        self._post_pay({'amount': 300, 'payment_date': '2026-03-12',
                        'source': '回款', 'method': '银行转账'})
        self._post_pay({'amount': 200, 'payment_date': '2026-03-12',
                        'source': '回款', 'method': '承兑汇票'})
        # 资金池可动用现金：期初1000 + 银行转账300；承兑汇票200 不计入
        bal = _pool_balance(self.dept, cfg, timezone.localdate())
        self.assertEqual(bal, Decimal('1300'))
        # 现金流分析仍计入承兑：collected = 500
        resp = self.client.get('/api/pk/ar/cashflow',
                               {'start_date': '2026-03-01', 'end_date': '2026-03-31',
                                'depts': self.dept}, **self.auth())
        self.assertEqual(resp.json()['data']['totals']['collected'][0], 500.0)

    def test_draft_status_default_persist_and_validate(self):
        # 承兑汇票默认「未承兑」；可指定「已承兑」；非四选一状态被拒
        d = self._post_pay({'amount': 100, 'payment_date': '2026-03-10',
                            'source': '回款', 'method': '承兑汇票'}).json()['data']
        self.assertEqual(d['draft_status'], '未承兑')     # 默认
        d2 = self._post_pay({'amount': 100, 'payment_date': '2026-03-11', 'source': '回款',
                            'method': '承兑汇票', 'draft_status': '已承兑'}).json()['data']
        self.assertEqual(d2['draft_status'], '已承兑')
        r = self._post_pay({'amount': 50, 'payment_date': '2026-03-12', 'source': '回款',
                           'method': '承兑汇票', 'draft_status': '部分承兑'})
        self.assertEqual(r.status_code, 400, r.content)
        # 非承兑汇票方式：承兑状态强制留空（即便客户端塞值）
        d3 = self._post_pay({'amount': 60, 'payment_date': '2026-03-13', 'source': '回款',
                            'method': '银行转账', 'draft_status': '已承兑'}).json()['data']
        self.assertEqual(d3['draft_status'], '')

    def test_accepted_draft_counts_as_pool_cash(self):
        """已承兑的承兑汇票视同现金进资金池；未承兑不进。PUT 兑付后即计入。"""
        from django.utils import timezone
        from ar.models import CashPoolConfig
        from ar.views.pool import _pool_balance
        cfg = CashPoolConfig.objects.create(
            delivery_dept=self.dept, initial_date=date(2026, 3, 1),
            initial_amount=Decimal('1000'))
        # 一笔已承兑（进池）、一笔未承兑（不进池）
        self._post_pay({'amount': 300, 'payment_date': '2026-03-12', 'source': '回款',
                        'method': '承兑汇票', 'draft_status': '已承兑'})
        pend = self._post_pay({'amount': 200, 'payment_date': '2026-03-12', 'source': '回款',
                              'method': '承兑汇票', 'draft_status': '未承兑'}).json()['data']
        today = timezone.localdate()
        self.assertEqual(_pool_balance(self.dept, cfg, today), Decimal('1300'))  # 期初1000+已承兑300
        # 把未承兑那笔改为已承兑 → 兑付到账，进池
        e = self.client.put(f'/api/pk/ar/records/{self.rec.id}/payments/{pend["id"]}',
                            data=json.dumps({'draft_status': '已承兑'}),
                            content_type='application/json', **self.auth())
        self.assertEqual(e.status_code, 200, e.content)
        self.assertEqual(e.json()['data']['draft_status'], '已承兑')
        self.assertEqual(_pool_balance(self.dept, cfg, today), Decimal('1500'))  # 两笔都进池
        # 现金流分析始终计入两笔（承兑无论是否兑付都是已实现现金流入）
        resp = self.client.get('/api/pk/ar/cashflow',
                               {'start_date': '2026-03-01', 'end_date': '2026-03-31',
                                'depts': self.dept}, **self.auth())
        self.assertEqual(resp.json()['data']['totals']['collected'][0], 500.0)

    def test_draft_status_invariant_no_empty_on_draft_method(self):
        """不变式：承兑汇票行的承兑状态恒为未承兑/已承兑，绝不为空——即便经方式往返、
        或直改 method 为承兑汇票而未带状态，save() 兜底为未承兑。"""
        from ar.models import ARPayment
        # 直接 ORM 造一条 method=承兑汇票 但 draft_status='' 的行 → save() 兜底未承兑
        p = ARPayment(ar_record=self.rec, payment_no=1, amount=Decimal('100'),
                      payment_date=date(2026, 3, 1), source='回款', method='承兑汇票')
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.draft_status, '未承兑')
        # PUT 把银行转账改为承兑汇票、不带 draft_status → 兜底未承兑（非空）
        pid = self._post_pay({'amount': 50, 'payment_date': '2026-03-02',
                             'source': '回款', 'method': '银行转账'}).json()['data']['id']
        e = self.client.put(f'/api/pk/ar/records/{self.rec.id}/payments/{pid}',
                            data=json.dumps({'method': '承兑汇票'}),
                            content_type='application/json', **self.auth())
        self.assertEqual(e.json()['data']['draft_status'], '未承兑')

    def test_ledger_filter_by_method_and_export_columns(self):
        self._post_pay({'amount': 100, 'payment_date': '2026-03-10', 'source': '回款', 'method': '微信'})
        self._post_pay({'amount': 200, 'payment_date': '2026-03-11', 'source': '回款', 'method': '现金'})
        # 按方式筛选
        items = self.client.get('/api/pk/ar/records/payments', {'method': '微信'},
                                **self.auth()).json()['data']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['method'], '微信')
        # 导出含「回款方式」「收款账户」列
        resp = self.client.get('/api/pk/ar/records/payments/export', **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(resp.getvalue()))
        headers = [c.value for c in wb.active[1]]
        self.assertIn('回款方式', headers)
        self.assertIn('收款账户', headers)

    def test_backfill_migration_maps_cash_to_bank(self):
        # 历史迁移逻辑：source='回款' 且 method='' → '银行转账'；非回款保持 ''
        from importlib import import_module
        from django.apps import apps as django_apps
        # 造 method='' 的历史态（bulk_create 跳过 save() 与 API 默认，保留空方式）
        p_cash = ARPayment(ar_record=self.rec, payment_no=1, amount=Decimal('100'),
                           payment_date=date(2026, 3, 1), source='回款', method='')
        p_int = ARPayment(ar_record=self.rec, payment_no=2, amount=Decimal('50'),
                          payment_date=date(2026, 3, 1), source='内部往来',
                          counterparty_dept=self.cp_dept, method='')
        ARPayment.objects.bulk_create([p_cash, p_int])
        mig = import_module('ar.migrations.0045_backfill_payment_method')
        mig.backfill_method(django_apps, None)          # 复用迁移正向函数
        p_cash.refresh_from_db(); p_int.refresh_from_db()
        self.assertEqual(p_cash.method, '银行转账')      # 回款回填银行转账
        self.assertEqual(p_int.method, '')               # 非回款保持空


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
