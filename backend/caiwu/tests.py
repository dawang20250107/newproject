import json
from decimal import Decimal

from django.test import Client, TestCase, override_settings
from openpyxl import Workbook

from caiwu.models import (
    BUSINESS_UNITS,
    FinancialEntry,
    FinancialTarget,
    ImportBatch,
    L1Category,
    L2Category,
    L3Category,
)
from caiwu.views import (
    _aggregate_report,
    _compute_l1_name_map,
    _detect_dept_ledger,
    _get_published_batches,
    _make_token,
    _parse_dept_ledger_rows,
)
from paikuan.models import PaikuanUser


REV = '\u4e3b\u8425\u4e1a\u52a1\u6536\u5165'
COST = '\u4e3b\u8425\u4e1a\u52a1\u6210\u672c'
TAX = '\u7a0e\u91d1\u6210\u672c'
OPERATING_GROSS = '\u8fd0\u8425\u6bdb\u5229'
SALES_EXP = '\u9500\u552e\u8d39\u7528'
MGMT_EXP = '\u7ba1\u7406\u8d39\u7528'
FIN_EXP = '\u8d22\u52a1\u8d39\u7528'
NONOP_REV = '\u8425\u4e1a\u5916\u6536\u5165'
NONOP_EXP = '\u8425\u4e1a\u5916\u652f\u51fa'
OPERATING_PROFIT = '\u7ecf\u8425\u6bdb\u5229'
GROUP_MGMT = '\u96c6\u56e2\u7ba1\u7406\u8d39\u7528'
NET_PROFIT = '\u7ecf\u8425\u51c0\u5229'

L1_SEEDS = [
    (REV, 10, False, 1, True),
    (COST, 20, False, -1, True),
    (TAX, 30, False, -1, False),
    (OPERATING_GROSS, 40, True, 1, False),
    (SALES_EXP, 50, False, -1, True),
    (MGMT_EXP, 60, False, -1, True),
    (FIN_EXP, 70, False, -1, False),
    (NONOP_REV, 80, False, 1, False),
    (NONOP_EXP, 90, False, -1, False),
    (OPERATING_PROFIT, 100, True, 1, False),
    (GROUP_MGMT, 110, False, -1, True),
    (NET_PROFIT, 120, True, 1, False),
]

BASE_AMOUNTS = {
    REV: '1000.00',
    COST: '600.00',
    TAX: '50.00',
    SALES_EXP: '30.00',
    MGMT_EXP: '40.00',
    FIN_EXP: '10.00',
    NONOP_REV: '20.00',
    NONOP_EXP: '5.00',
    GROUP_MGMT: '25.00',
}

CURRENT_AMOUNTS = {
    REV: '1200.00',
    COST: '650.00',
    TAX: '60.00',
    SALES_EXP: '35.00',
    MGMT_EXP: '45.00',
    FIN_EXP: '12.00',
    NONOP_REV: '25.00',
    NONOP_EXP: '8.00',
    GROUP_MGMT: '30.00',
}


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class CaiwuCalculationLogicTests(TestCase):
    # caiwu 已并入 default 库（平台整合阶段1），测试不再需要独立的 caiwu alias。
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        for name, sort_order, is_calculated, sign, is_profit_driver in L1_SEEDS:
            L1Category.objects.update_or_create(
                name=name,
                defaults={
                    'sort_order': sort_order,
                    'is_calculated': is_calculated,
                    'sign': sign,
                    'is_profit_driver': is_profit_driver,
                },
            )
        # Unified platform account (Stage 2+3): auth + uploaded_by both use it.
        cls.admin = PaikuanUser(
            phone='13900000000',
            name='Finance Admin',
            role='super_admin',
            job_title='finance_director',
            departments=[],
            is_active=True,
            is_approved=True,
        )
        cls.admin.set_password('Test123456')
        cls.admin.save()

    def setUp(self):
        self.client = Client()
        self.bu = BUSINESS_UNITS[0]
        self.l1 = {c.name: c for c in L1Category.objects.order_by('sort_order', 'id')}

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(self.admin)}'}

    def create_batch(
        self,
        year=2026,
        month=5,
        batch_type=ImportBatch.TYPE_DEPT,
        status=ImportBatch.STATUS_PUBLISHED,
        amounts=None,
        bu=None,
    ):
        batch = ImportBatch.objects.create(
            business_unit=bu or self.bu,
            year=year,
            month=month,
            batch_type=batch_type,
            status=status,
            uploaded_by=self.admin,
            row_count=len(amounts or {}),
            file_name='logic-test.xlsx',
        )
        for name, amount in (amounts or {}).items():
            FinancialEntry.objects.create(
                batch=batch,
                l1=self.l1[name],
                amount=Decimal(str(amount)),
            )
        return batch

    def response_json(self, resp):
        return json.loads(resp.content.decode('utf-8'))

    def test_batch_uploader_is_unified_account(self):
        # Regression: after the platform merge the uploader FK targets
        # PaikuanUser; to_dict() must surface that account's name, not None.
        batch = self.create_batch(amounts={REV: '1.00'})
        self.assertEqual(batch.uploaded_by_id, self.admin.id)
        self.assertEqual(batch.to_dict()['uploaded_by'], self.admin.name)

    def test_l1_formula_chain_computes_bottom_line(self):
        l1_cats = list(L1Category.objects.order_by('sort_order', 'id'))
        raw_by_id = {self.l1[name].id: Decimal(amount) for name, amount in BASE_AMOUNTS.items()}

        name_map, _ = _compute_l1_name_map(l1_cats, raw_by_id)

        self.assertEqual(name_map[OPERATING_GROSS], 350.0)
        self.assertEqual(name_map[OPERATING_PROFIT], 285.0)
        self.assertEqual(name_map[NET_PROFIT], 260.0)

    def test_report_aggregates_department_detail_only(self):
        self.create_batch(amounts=BASE_AMOUNTS, batch_type=ImportBatch.TYPE_DEPT)
        self.create_batch(
            amounts={REV: '9999.00', COST: '1.00'},
            batch_type=ImportBatch.TYPE_PL,
        )

        rows = _aggregate_report(_get_published_batches([self.bu], 2026, 5), 1)
        by_name = {row['l1_name']: row['amount'] for row in rows}

        self.assertEqual(by_name[REV], 1000.0)
        self.assertEqual(by_name[COST], 600.0)
        self.assertEqual(by_name[NET_PROFIT], 260.0)

    def test_publish_replaces_same_period_and_type_only(self):
        old_dept = self.create_batch(amounts=BASE_AMOUNTS, batch_type=ImportBatch.TYPE_DEPT)
        old_pl = self.create_batch(amounts={REV: '9999.00'}, batch_type=ImportBatch.TYPE_PL)
        draft_dept = self.create_batch(
            amounts=CURRENT_AMOUNTS,
            batch_type=ImportBatch.TYPE_DEPT,
            status=ImportBatch.STATUS_DRAFT,
        )

        resp = self.client.put(f'/api/cw/batches/{draft_dept.id}/publish', **self.auth())

        self.assertEqual(resp.status_code, 200, self.response_json(resp))
        self.assertFalse(ImportBatch.objects.filter(id=old_dept.id).exists())
        self.assertTrue(ImportBatch.objects.filter(id=old_pl.id, status=ImportBatch.STATUS_PUBLISHED).exists())
        draft_dept.refresh_from_db()
        self.assertEqual(draft_dept.status, ImportBatch.STATUS_PUBLISHED)

    def test_waterfall_factors_bridge_net_profit_delta(self):
        self.create_batch(year=2026, month=4, amounts=BASE_AMOUNTS)
        self.create_batch(year=2026, month=5, amounts=CURRENT_AMOUNTS)

        resp = self.client.get(
            '/api/cw/charts/waterfall',
            {
                'bu': self.bu,
                'year': 2026,
                'month': 5,
                'compare_year': 2026,
                'compare_month': 4,
            },
            **self.auth(),
        )
        payload = self.response_json(resp)

        self.assertEqual(resp.status_code, 200, payload)
        data = payload['data']
        base_total = Decimal(str(data['base_period']['total']))
        current_total = Decimal(str(data['current_period']['total']))
        factor_delta = sum(Decimal(str(f['delta'])) for f in data['factors'])
        waterfall_delta = sum(
            Decimal(str(w['value']))
            for w in data['waterfall']
            if w['type'] in ('increase', 'decrease')
        )

        self.assertEqual(base_total, Decimal('260.0'))
        self.assertEqual(current_total, Decimal('385.0'))
        self.assertEqual(factor_delta, current_total - base_total)
        self.assertEqual(waterfall_delta, current_total - base_total)

    def test_waterfall_bridge_closes_when_current_period_is_a_loss(self):
        # Regression: loss period (negative terminal). The terminal bar is drawn
        # 0→value (below the axis); the last decrease factor must land exactly on
        # it, i.e. base + Σ(waterfall factor bars) == current total — no floating gap.
        self.create_batch(year=2026, month=4, amounts=BASE_AMOUNTS)
        loss_amounts = dict(BASE_AMOUNTS, **{REV: '100.00', COST: '900.00'})
        self.create_batch(year=2026, month=5, amounts=loss_amounts)

        resp = self.client.get(
            '/api/cw/charts/waterfall',
            {'bu': self.bu, 'year': 2026, 'month': 5,
             'compare_year': 2026, 'compare_month': 4},
            **self.auth(),
        )
        payload = self.response_json(resp)
        self.assertEqual(resp.status_code, 200, payload)
        data = payload['data']

        base_total = Decimal(str(data['base_period']['total']))
        current_total = Decimal(str(data['current_period']['total']))
        self.assertLess(current_total, 0)  # genuine loss

        bars = data['waterfall']
        self.assertEqual(bars[0]['type'], 'base')
        self.assertEqual(bars[-1]['type'], 'total')
        factor_sum = sum(
            Decimal(str(b['value'])) for b in bars
            if b['type'] in ('increase', 'decrease')
        )
        # Bridge closes: terminal value is reached exactly by the cumulative.
        self.assertEqual(base_total + factor_sum, current_total)
        self.assertEqual(Decimal(str(bars[-1]['value'])), current_total)

    def test_closed_period_ledger_parser_excludes_carry_forward_and_summary_rows(self):
        wb = Workbook()
        ws = wb.active
        ws.append([
            '\u90e8\u95e8\u540d\u79f0',
            '\u79d1\u76ee\u7f16\u7801',
            '\u79d1\u76ee\u540d\u79f0',
            '\u6458\u8981',
            '\u501f\u65b9',
            '\u8d37\u65b9',
        ])
        ws.append([self.bu, '6001.01', '\u9500\u552e\u6536\u5165', '\u51ed\u8bc1001', 0, 1000])
        ws.append([self.bu, '6001.01', '\u9500\u552e\u6536\u5165', '\u7ed3\u8f6c\u635f\u76ca', 1000, 0])
        ws.append([self.bu, '6001.01', '\u9500\u552e\u6536\u5165', '\u672c\u671f\u5408\u8ba1', 1000, 1000])
        ws.append([self.bu, '6401.01', '\u8fd0\u8f93\u6210\u672c', '\u51ed\u8bc1002', 600, 0])
        ws.append([self.bu, '6401.01', '\u8fd0\u8f93\u6210\u672c', '\u672c\u5e74\u7d2f\u8ba1', 600, 0])

        data_start, col_map = _detect_dept_ledger(ws)
        parsed, errors = _parse_dept_ledger_rows(
            ws,
            data_start,
            col_map,
            self.bu,
            self.l1,
            {c.name: c for c in L2Category.objects.filter(business_unit=self.bu)},
            {(c.l1_category_id, c.name): c for c in L3Category.objects.filter(business_unit=self.bu)},
        )
        by_name = {}
        for row in parsed:
            by_name[row['l1_name']] = by_name.get(row['l1_name'], Decimal('0')) + row['amount']

        self.assertEqual(errors, [])
        self.assertEqual(by_name[REV], Decimal('1000'))
        self.assertEqual(by_name[COST], Decimal('600'))
        self.assertEqual(len(parsed), 2)


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class CaiwuUnifiedPermissionTests(TestCase):
    """Stage 2-4: caiwu auth/permissions are driven by the paikuan platform.
    These lock in the cross-module behaviour (page gating + shared cache)."""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        for name, sort_order, is_calculated, sign, is_profit_driver in L1_SEEDS:
            L1Category.objects.update_or_create(
                name=name,
                defaults={'sort_order': sort_order, 'is_calculated': is_calculated,
                          'sign': sign, 'is_profit_driver': is_profit_driver},
            )
        cls.bu = BUSINESS_UNITS[0]
        # super_admin (paikuan) — manages permissions
        cls.admin = PaikuanUser(phone='13700000000', name='Admin', role='super_admin',
                                job_title='', departments=[], is_active=True, is_approved=True)
        cls.admin.set_password('Test123456'); cls.admin.save()
        # finance_director — should get full 财务分析 access by default
        cls.fin = PaikuanUser(phone='13700000001', name='Finance', role='viewer',
                              job_title='finance_director', departments=[cls.bu],
                              is_active=True, is_approved=True)
        cls.fin.set_password('Test123456'); cls.fin.save()
        # cashier — should have NO 财务分析 access by default
        cls.cashier = PaikuanUser(phone='13700000002', name='Cashier', role='viewer',
                                  job_title='cashier', departments=[cls.bu],
                                  is_active=True, is_approved=True)
        cls.cashier.set_password('Test123456'); cls.cashier.save()

    def setUp(self):
        self.client = Client()
        # Clear caches so a prior test's stored JobPermission doesn't leak.
        from paikuan.views import _invalidate_perm_cache as pk_inv
        from caiwu.views import _invalidate_perm_cache as cw_inv
        pk_inv(); cw_inv()

    def hdr(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(user)}'}

    def jj(self, resp):
        return json.loads(resp.content.decode('utf-8'))

    def test_finance_director_can_access_report(self):
        resp = self.client.get('/api/cw/report',
                               {'year': 2026, 'month': 5, 'bu': self.bu, 'level': 1},
                               **self.hdr(self.fin))
        self.assertEqual(resp.status_code, 200, self.jj(resp))

    def test_cashier_denied_report_and_upload(self):
        r1 = self.client.get('/api/cw/report',
                             {'year': 2026, 'month': 5, 'bu': self.bu, 'level': 1},
                             **self.hdr(self.cashier))
        self.assertEqual(r1.status_code, 403, self.jj(r1))
        r2 = self.client.post('/api/cw/batches/upload', {'bu': self.bu, 'year': 2026, 'month': 5},
                              **self.hdr(self.cashier))
        self.assertEqual(r2.status_code, 403, self.jj(r2))

    def test_paikuan_permission_edit_invalidates_caiwu_cache(self):
        # finance_director starts with caiwu_report access
        before = self.client.get('/api/cw/report',
                                 {'year': 2026, 'month': 5, 'bu': self.bu, 'level': 1},
                                 **self.hdr(self.fin))
        self.assertEqual(before.status_code, 200, self.jj(before))

        # super_admin disables 财务分析·报表 for finance_director via the paikuan UI path
        perms = self.jj(self.client.get('/api/pk/permissions', **self.hdr(self.admin)))
        cfg = next(j['config'] for j in perms['data']['jobs'] if j['job_title'] == 'finance_director')
        cfg['pages']['caiwu_report'] = False
        put = self.client.put('/api/pk/permissions/finance_director',
                              data=json.dumps({'config': cfg}),
                              content_type='application/json', **self.hdr(self.admin))
        self.assertEqual(put.status_code, 200, self.jj(put))

        # Change must take effect immediately (caiwu cache invalidated)
        after = self.client.get('/api/cw/report',
                                {'year': 2026, 'month': 5, 'bu': self.bu, 'level': 1},
                                **self.hdr(self.fin))
        self.assertEqual(after.status_code, 403, self.jj(after))


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class CaiwuMetricsAndTargetsTests(TestCase):
    """指标管理 / 财务驾驶舱：目标录入校验 + 完成情况取数（达成率/环比/同比/YTD）。"""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        for name, sort_order, is_calculated, sign, is_profit_driver in L1_SEEDS:
            L1Category.objects.update_or_create(
                name=name,
                defaults={'sort_order': sort_order, 'is_calculated': is_calculated,
                          'sign': sign, 'is_profit_driver': is_profit_driver},
            )
        cls.admin = PaikuanUser(phone='13900000009', name='Metrics Admin',
                                role='super_admin', job_title='finance_director',
                                departments=[], is_active=True, is_approved=True)
        cls.admin.set_password('Test123456')
        cls.admin.save()

    def setUp(self):
        self.client = Client()
        self.bu = BUSINESS_UNITS[1]   # 一个真实事业部（非集团总部）
        self.l1 = {c.name: c for c in L1Category.objects.all()}

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(self.admin)}'}

    def jj(self, resp):
        return json.loads(resp.content.decode('utf-8'))

    def mk(self, year, month, rev, cost):
        b = ImportBatch.objects.create(
            business_unit=self.bu, year=year, month=month,
            batch_type=ImportBatch.TYPE_DEPT, status=ImportBatch.STATUS_PUBLISHED,
            uploaded_by=self.admin, row_count=2, file_name='m.xlsx')
        FinancialEntry.objects.create(batch=b, l1=self.l1[REV], amount=Decimal(str(rev)))
        FinancialEntry.objects.create(batch=b, l1=self.l1[COST], amount=Decimal(str(cost)))
        return b

    def post_targets(self, items, year=2026):
        return self.client.post('/api/cw/targets',
                                data=json.dumps({'year': year, 'items': items}),
                                content_type='application/json', **self.auth())

    # ── 目标录入校验 ──────────────────────────────────────────────────────────
    def _full_year_items(self, monthly_rev, monthly_prof, annual_rev, annual_prof):
        items = [{'business_unit': self.bu, 'month': m,
                  'target_revenue': monthly_rev, 'target_profit': monthly_prof}
                 for m in range(1, 13)]
        items.append({'business_unit': self.bu, 'month': 0,
                      'target_revenue': annual_rev, 'target_profit': annual_prof})
        return items

    def test_month_sum_must_equal_annual(self):
        # 12×100 = 1200 收入；年度填 1300 → 拒绝
        bad = self.post_targets(self._full_year_items(100, 10, 1300, 120))
        self.assertEqual(bad.status_code, 400, self.jj(bad))
        self.assertIn('收入', self.jj(bad)['error'])
        # 年度填 1200 收入 / 120 利润（=12×10）→ 通过
        good = self.post_targets(self._full_year_items(100, 10, 1200, 120))
        self.assertEqual(good.status_code, 200, self.jj(good))
        self.assertEqual(self.jj(good)['data']['saved'], 13)

    def test_validation_merges_with_existing_db(self):
        # 数据库已存 12 个月（合计 1200 收入）
        for m in range(1, 13):
            FinancialTarget.objects.create(business_unit=self.bu, year=2026, month=m,
                                           target_revenue=Decimal('100'), target_profit=Decimal('10'))
        # 仅提交一个与库内 12 月不符的年度目标 → 应被拒绝（基于合并后的状态）
        bad = self.post_targets([{'business_unit': self.bu, 'month': 0,
                                  'target_revenue': 2000, 'target_profit': 120}])
        self.assertEqual(bad.status_code, 400, self.jj(bad))
        # 提交相符的年度目标 → 通过
        good = self.post_targets([{'business_unit': self.bu, 'month': 0,
                                   'target_revenue': 1200, 'target_profit': 120}])
        self.assertEqual(good.status_code, 200, self.jj(good))

    # ── 完成情况取数 ──────────────────────────────────────────────────────────
    def test_metrics_rate_mom_yoy_ytd(self):
        self.mk(2026, 4, 150, 100)   # 上月：利润 50
        self.mk(2026, 5, 200, 130)   # 本月：利润 70
        self.mk(2025, 5, 180, 120)   # 去年同月：利润 60
        FinancialTarget.objects.create(business_unit=self.bu, year=2026, month=5,
                                       target_revenue=Decimal('250'), target_profit=Decimal('60'))
        FinancialTarget.objects.create(business_unit=self.bu, year=2026, month=0,
                                       target_revenue=Decimal('3000'), target_profit=Decimal('700'))
        resp = self.client.get('/api/cw/metrics',
                               {'year': 2026, 'month': 5, 'bu': self.bu}, **self.auth())
        self.assertEqual(resp.status_code, 200, self.jj(resp))
        m = next(b for b in self.jj(resp)['data']['bus'] if b['business_unit'] == self.bu)
        self.assertAlmostEqual(m['month']['actual_revenue'], 200)
        self.assertAlmostEqual(m['month']['actual_profit'], 70)
        self.assertAlmostEqual(m['month']['revenue_rate'], 80.0)        # 200/250
        self.assertAlmostEqual(m['month']['profit_rate'], 116.7, places=1)  # 70/60
        self.assertAlmostEqual(m['month']['revenue_mom'], 33.3, places=1)   # (200-150)/150
        self.assertAlmostEqual(m['month']['profit_mom'], 40.0, places=1)    # (70-50)/50
        self.assertAlmostEqual(m['month']['revenue_yoy'], 11.1, places=1)   # (200-180)/180
        self.assertAlmostEqual(m['ytd']['actual_revenue'], 350)            # 150+200
        self.assertAlmostEqual(m['ytd']['actual_profit'], 120)            # 50+70

    def test_cockpit_overview_and_12_month_trend(self):
        self.mk(2026, 5, 200, 130)
        FinancialTarget.objects.create(business_unit=self.bu, year=2026, month=5,
                                       target_revenue=Decimal('250'), target_profit=Decimal('60'))
        resp = self.client.get('/api/cw/cockpit',
                               {'year': 2026, 'month': 5, 'bu': self.bu}, **self.auth())
        self.assertEqual(resp.status_code, 200, self.jj(resp))
        data = self.jj(resp)['data']
        self.assertEqual(len(data['trend']), 12)
        m5 = next(t for t in data['trend'] if t['month'] == 5)
        self.assertAlmostEqual(m5['actual_revenue'], 200)
        self.assertAlmostEqual(m5['target_revenue'], 250)
        self.assertAlmostEqual(data['overview']['month']['revenue_rate'], 80.0)
        # MoM/YoY 键应始终存在（无对比期时为 None）
        self.assertIn('revenue_mom', data['overview']['month'])

    # ── 驾驶舱全局 AI 分析（mock 掉外部模型调用）─────────────────────────────
    def test_cockpit_ai_uses_pro_model_and_group_scope(self):
        from unittest import mock
        from django.conf import settings
        self.mk(2026, 5, 200, 130)
        captured = {}

        def fake_chat(messages, timeout=90, model=None, max_tokens=1800):
            captured['model'] = model
            captured['max_tokens'] = max_tokens
            captured['prompt'] = messages[-1]['content']
            return '【模拟分析】全集团经营稳健。'

        with mock.patch('caiwu.views._deepseek_chat', fake_chat):
            resp = self.client.post(
                '/api/cw/cockpit/ai-analysis',
                data=json.dumps({'year': 2026, 'month': 5}),
                content_type='application/json', **self.auth())
        self.assertEqual(resp.status_code, 200, self.jj(resp))
        data = self.jj(resp)['data']
        self.assertEqual(data['model'], settings.DEEPSEEK_PRO_MODEL)
        self.assertEqual(data['scope'], '全集团')
        self.assertIn('analysis', data)
        # 用更强模型 + 更大 token 预算，提示词带全集团口径
        self.assertEqual(captured['model'], settings.DEEPSEEK_PRO_MODEL)
        self.assertGreaterEqual(captured['max_tokens'], 3000)
        self.assertIn('全集团', captured['prompt'])

    def test_cockpit_ai_no_data_returns_error(self):
        from unittest import mock
        with mock.patch('caiwu.views._deepseek_chat') as m:
            resp = self.client.post(
                '/api/cw/cockpit/ai-analysis',
                data=json.dumps({'year': 2026, 'month': 7}),
                content_type='application/json', **self.auth())
        self.assertEqual(resp.status_code, 400, self.jj(resp))
        m.assert_not_called()   # 无数据时不应调用外部模型
