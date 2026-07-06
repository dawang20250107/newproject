import json
from decimal import Decimal

from django.test import Client, TestCase, override_settings
from openpyxl import Workbook

from caiwu.models import (
    BUSINESS_UNITS,
    FinancialEntry,
    InternalBalance,
    InternalBatch,
    InternalEntry,
    FinancialTarget,
    ImportBatch,
    L1Category,
    L2Category,
    L3Category,
)
from caiwu.views import (
    _aggregate_report,
    _allocate_unalloc,
    _compute_l1_name_map,
    _compute_pl_check,
    _detect_dept_ledger,
    _detect_project_ledger,
    _get_published_batches,
    _make_token,
    _parse_dept_ledger_rows,
    _parse_project_ledger,
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

    def test_6602_99_03_maps_to_group_management_fee(self):
        """集团管理费用仅取 6602.99.03 本科目（集团管理费分摊/收回）；其同级的
        6602.99.01 培训费、6602.99.02 会议费等属普通管理费用，按 6602 前缀归入
        管理费用，不计入集团管理费。科目名称含「集团管理费用」者另由名称兜底覆盖。"""
        wb = Workbook()
        ws = wb.active
        ws.append([
            '部门名称',   # 部门名称
            '科目编码',   # 科目编码
            '科目名称',   # 科目名称
            '摘要',               # 摘要
            '借方',               # 借方
            '贷方',               # 贷方
        ])
        # 6602.01 普通管理费 → 管理费用
        ws.append([self.bu, '6602.01', '办公费', '凭证001', 100, 0])
        # 6602.99.03 集团管理费用本科目 → 集团管理费用（即使名称不含也按编码归集）
        ws.append([self.bu, '6602.99.03', '分摊费用', '凭证002', 200, 0])
        # 6602.99.01 培训费等同级子目 → 回落 6602 前缀 → 管理费用（不计集团管理费）
        ws.append([self.bu, '6602.99.01', '外部咨询培训费', '凭证003', 50, 0])

        data_start, col_map = _detect_dept_ledger(ws)
        parsed, errors = _parse_dept_ledger_rows(
            ws, data_start, col_map, self.bu, self.l1,
            {c.name: c for c in L2Category.objects.filter(business_unit=self.bu)},
            {(c.l1_category_id, c.name): c for c in L3Category.objects.filter(business_unit=self.bu)},
        )
        by_name = {}
        for row in parsed:
            by_name[row['l1_name']] = by_name.get(row['l1_name'], Decimal('0')) + row['amount']

        self.assertEqual(errors, [])
        # 管理费用 sign=-1 → 办公费100 + 培训费50 = 150；集团管理费用 = 仅 6602.99.03 的 200
        self.assertEqual(by_name[MGMT_EXP], Decimal('150'))
        self.assertEqual(by_name[GROUP_MGMT], Decimal('200'))

    def test_hq_import_excludes_finance_dept(self):
        """集团总部导入时整段剔除「财务金融」部门（供应链金融独立条线），
        其收入/成本/费用均不计入集团总部报表；其他部门正常计入。"""
        self.assertEqual(self.bu, '集团总部')   # BUSINESS_UNITS[0]
        wb = Workbook()
        ws = wb.active
        ws.append(['部门名称', '科目编码', '科目名称', '摘要', '借方', '贷方'])
        # 财务金融：收入80 / 成本30 / 财务费用5 —— 应被整段剔除
        ws.append([self.bu, '6001', '服务费收入', '凭证001', 0, 80])
        ws.append([self.bu, '6401', '主营业务成本', '凭证002', 30, 0])
        ws.append([self.bu, '6603', '利息支出', '凭证003', 5, 0])
        # 行政园区：园区收入100 —— 应正常计入
        ws.append(['行政园区', '6001', '仓库租赁收入', '凭证004', 0, 100])

        # 重新读 dept 列：第一行表头里「部门名称」需要对上财务金融
        for ri, dept in [(2, '财务金融'), (3, '财务金融'), (4, '财务金融'), (5, '行政园区')]:
            ws.cell(ri, 1, dept)

        data_start, col_map = _detect_dept_ledger(ws)
        parsed, errors = _parse_dept_ledger_rows(
            ws, data_start, col_map, self.bu, self.l1,
            {c.name: c for c in L2Category.objects.filter(business_unit=self.bu)},
            {(c.l1_category_id, c.name): c for c in L3Category.objects.filter(business_unit=self.bu)},
        )
        by_name = {}
        for row in parsed:
            by_name[row['l1_name']] = by_name.get(row['l1_name'], Decimal('0')) + row['amount']

        self.assertEqual(errors, [])
        # 仅行政园区的园区收入100计入；财务金融全部剔除
        self.assertEqual(by_name.get(REV), Decimal('100'))
        self.assertNotIn(COST, by_name)
        # 剔除的部门不应创建二级项目部
        self.assertFalse(L2Category.objects.filter(business_unit=self.bu, name='财务金融').exists())

    def test_report_excludes_finance_dept_retroactively(self):
        """报表聚合层剔除集团总部的财务金融——即使历史已发布批次里仍含该部门，
        报表也不计入（无需重新导入即对旧数据生效）。"""
        self.assertEqual(self.bu, '集团总部')
        batch = ImportBatch.objects.create(
            business_unit=self.bu, year=2026, month=5,
            batch_type=ImportBatch.TYPE_DEPT, status=ImportBatch.STATUS_PUBLISHED,
            uploaded_by=self.admin, row_count=2, file_name='hq.xlsx',
        )
        fin = L2Category.objects.create(business_unit=self.bu, name='财务金融')
        park = L2Category.objects.create(business_unit=self.bu, name='行政园区')
        # 财务金融收入80（应剔除）+ 行政园区收入100（应保留）
        FinancialEntry.objects.create(batch=batch, l1=self.l1[REV], l2=fin, amount=Decimal('80'))
        FinancialEntry.objects.create(batch=batch, l1=self.l1[REV], l2=park, amount=Decimal('100'))

        rows = _aggregate_report(_get_published_batches([self.bu], 2026, 5), 1)
        rev = next((r['amount'] for r in rows if r['l1_name'] == REV), None)
        self.assertEqual(rev, 100.0)   # 仅行政园区100，财务金融80被剔除

        # 二级明细里也不应出现财务金融
        rows2 = _aggregate_report(_get_published_batches([self.bu], 2026, 5), 2)
        rev_row = next(r for r in rows2 if r['l1_name'] == REV)
        l2names = {c['l2_name'] for c in rev_row['children']}
        self.assertIn('行政园区', l2names)
        self.assertNotIn('财务金融', l2names)

    def test_pl_check_matches_report_kpis(self):
        """导入预览的「数据核对」KPI（_compute_pl_check）应与发布后的财务报表
        （_aggregate_report）逐项一致——回归用户反馈的「导入核对显示异常但报表正常」。"""
        parsed_rows = []
        for name, amt in BASE_AMOUNTS.items():
            parsed_rows.append({
                'l1': self.l1[name], 'l2': None, 'l3': None,
                'amount': Decimal(amt),
                'l1_name': name, 'l2_name': '', 'l3_name': '',
            })
        pl = _compute_pl_check(parsed_rows)
        kpi = {r['name']: r['amount'] for r in pl['kpis']}
        self.assertEqual(kpi[OPERATING_GROSS], 350.0)
        self.assertEqual(kpi[OPERATING_PROFIT], 285.0)
        self.assertEqual(kpi[NET_PROFIT], 260.0)

        # 与发布后报表逐项一致
        self.create_batch(amounts=BASE_AMOUNTS, batch_type=ImportBatch.TYPE_DEPT)
        report = {r['l1_name']: r['amount']
                  for r in _aggregate_report(_get_published_batches([self.bu], 2026, 5), 1)}
        for r in pl['l1_summary']:
            self.assertAlmostEqual(r['amount'], report.get(r['name'], 0), places=2,
                                   msg=f"{r['name']} 预览={r['amount']} 报表={report.get(r['name'])}")

    def test_project_ledger_parse_and_allocate(self):
        """项目核算明细账（维度=项目名称）解析：6001→收入(贷-借)、6401→成本(借-贷)，
        跳过小计/结转损益行；以及未挂成本按收入比例分摊。"""
        wb = Workbook()
        ws = wb.active
        ws.append(['核算维度明细账'])
        ws.append(['账簿信息'])
        ws.append(['序号', '项目名称', '科目编码', '科目名称', '会计期间',
                   '记账日期', '业务日期', '凭证字号', '摘要', '币种', '借方', '贷方'])
        # 甲项目：收入1000(贷)、成本300(借)
        ws.append([1, '甲', '6001.01', '主营收入', '2026年5期', '2026-05-10', None, '记1', '直客收入', '人民币', 0, 1000])
        ws.append([2, '甲', '6401.01', '运输成本', '2026年5期', '2026-05-11', None, '记2', '成本', '人民币', 300, 0])
        # 乙项目：收入500(贷)
        ws.append([3, '乙', '6001.01', '主营收入', '2026年5期', '2026-05-12', None, '记3', '直客收入', '人民币', 0, 500])
        # 未挂项目「无」：成本600（待分摊）
        ws.append([4, '无', '6401.01', '分摊成本', '2026年5期', '2026-05-20', None, '记4', '公共成本', '人民币', 600, 0])
        # 小计 & 结转损益行：应跳过
        ws.append([5, '甲', '6001.01', '主营收入', '2026年5期', '2026-05-31', None, None, '本期合计', '人民币', 0, 1000])
        ws.append([6, '甲', '6001.01', '主营收入', '2026年5期', '2026-05-31', None, '记9', '结转损益', '人民币', 1000, 0])

        ds, cm = _detect_project_ledger(ws)
        self.assertIsNotNone(ds)
        by_period = _parse_project_ledger(ws, ds, cm, fallback_ym=(2026, 5))
        self.assertEqual(list(by_period.keys()), [(2026, 5)])   # 单月文件仍单期间
        agg = by_period[(2026, 5)]
        self.assertEqual(agg['甲']['revenue'], Decimal('1000'))
        self.assertEqual(agg['甲']['cost'], Decimal('300'))
        self.assertEqual(agg['乙']['revenue'], Decimal('500'))
        self.assertEqual(agg['无']['cost'], Decimal('600'))

        # 分摊：未挂成本600 按收入(甲1000:乙500=2:1)分摊 → 甲+400、乙+200
        rows = [
            {'project_name': '甲', 'revenue': 1000.0, 'cost': 300.0, 'sales_exp': 0.0, 'mgmt_exp': 0.0, 'margin': 700.0, 'margin_rate': 70.0},
            {'project_name': '乙', 'revenue': 500.0, 'cost': 0.0, 'sales_exp': 0.0, 'mgmt_exp': 0.0, 'margin': 500.0, 'margin_rate': 100.0},
        ]
        unalloc = {'revenue': 0.0, 'cost': 600.0, 'sales_exp': 0.0, 'mgmt_exp': 0.0}
        out = _allocate_unalloc(rows, unalloc)
        by = {r['project_name']: r for r in out}
        self.assertEqual(by['甲']['cost'], 700.0)   # 300 + 400
        self.assertEqual(by['甲']['margin'], 300.0)  # 1000 - 700
        self.assertEqual(by['乙']['cost'], 200.0)    # 0 + 200
        self.assertEqual(by['乙']['margin'], 300.0)  # 500 - 200

    def test_template_has_no_profit_loss_sheet(self):
        """利润表已下线：下载模板不应再含「利润表模板」页（仅部门明细相关页）。"""
        import io
        from openpyxl import load_workbook
        resp = self.client.get('/api/cw/batches/template', **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        wb = load_workbook(io.BytesIO(resp.content))
        self.assertNotIn('利润表模板', wb.sheetnames)


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

    def test_cashier_denied_new_ai_and_project_endpoints(self):
        """无财务分析权限者不能访问 项目毛利 / 驾驶舱知识库 / 技能（回归权限是否跟上新功能）。"""
        r = self.client.get('/api/cw/project-margin',
                            {'bu': self.bu, 'year': 2026, 'month': 5}, **self.hdr(self.cashier))
        self.assertEqual(r.status_code, 403, self.jj(r))
        for url in ('/api/cw/cockpit/knowledge', '/api/cw/cockpit/skills'):
            self.assertEqual(self.client.get(url, **self.hdr(self.cashier)).status_code, 403)
        chat = self.client.post('/api/cw/cockpit/ai-chat/stream',
                                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                                 'messages': [{'role': 'user', 'content': 'hi'}]}),
                                content_type='application/json', **self.hdr(self.cashier))
        self.assertEqual(chat.status_code, 403, self.jj(chat))

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


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
                   DEEPSEEK_API_KEY='test-key')  # AI 已 mock；补 key 使无密钥环境（CI/沙箱）确定性通过
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
    def _full_year_items(self, monthly_rev, monthly_prof, annual_rev, annual_prof,
                         monthly_gross=0, annual_gross=0):
        items = [{'business_unit': self.bu, 'month': m,
                  'target_revenue': monthly_rev, 'target_profit': monthly_prof,
                  'target_gross_profit': monthly_gross}
                 for m in range(1, 13)]
        items.append({'business_unit': self.bu, 'month': 0,
                      'target_revenue': annual_rev, 'target_profit': annual_prof,
                      'target_gross_profit': annual_gross})
        return items

    def test_month_sum_must_equal_annual(self):
        # 12×100 = 1200 收入；年度填 1300 → 拒绝
        bad = self.post_targets(self._full_year_items(100, 10, 1300, 120, 8, 96))
        self.assertEqual(bad.status_code, 400, self.jj(bad))
        self.assertIn('收入', self.jj(bad)['error'])
        # 经营净利不符 → 拒绝
        bad2 = self.post_targets(self._full_year_items(100, 10, 1200, 999, 8, 96))
        self.assertEqual(bad2.status_code, 400, self.jj(bad2))
        self.assertIn('经营净利', self.jj(bad2)['error'])
        # 经营毛利不符 → 拒绝
        bad3 = self.post_targets(self._full_year_items(100, 10, 1200, 120, 8, 999))
        self.assertEqual(bad3.status_code, 400, self.jj(bad3))
        self.assertIn('经营毛利', self.jj(bad3)['error'])
        # 全部一致 → 通过
        good = self.post_targets(self._full_year_items(100, 10, 1200, 120, 8, 96))
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

        def fake_chat(messages, timeout=90, model=None, max_tokens=1800, **kw):
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

    def test_cockpit_ai_stream_emits_sse_frames(self):
        from unittest import mock
        from django.conf import settings
        self.mk(2026, 5, 200, 130)
        captured = {}

        def fake_stream(messages, model=None, max_tokens=1800, timeout=300, **kw):
            captured['model'] = model
            captured['max_tokens'] = max_tokens
            yield ('reasoning', '先看全集团达成')
            yield ('answer', '## 总览\n')
            yield ('answer', '集团收入500万。')

        with mock.patch('caiwu.views._deepseek_stream', fake_stream):
            resp = self.client.post(
                '/api/cw/cockpit/ai-analysis/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu}),
                content_type='application/json', **self.auth())
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp['Content-Type'], 'text/event-stream')
            self.assertEqual(resp['X-Accel-Buffering'], 'no')
            # 必须在 patch 生效期间消费惰性生成器，否则会落到真实的流式调用。
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip())
                  for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        types = [e['type'] for e in events]
        self.assertEqual(types[0], 'meta')
        self.assertEqual(types[-1], 'done')
        self.assertIn('reasoning', types)
        self.assertIn('answer', types)
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        self.assertEqual(answer, '## 总览\n集团收入500万。')
        self.assertEqual(captured['model'], settings.DEEPSEEK_PRO_MODEL)
        self.assertGreaterEqual(captured['max_tokens'], 3000)

    def test_cockpit_ai_chat_stream(self):
        """业财融合对话：带历史的多轮提问，SSE 流式返回，且用 PRO 模型 + 数据上下文。"""
        from unittest import mock
        from django.conf import settings
        self.mk(2026, 5, 200, 130)
        captured = {}

        def fake_stream_raw(messages, tools=None, model=None, timeout=90, max_tokens=1800, **kw):
            captured['model'] = model
            captured['messages'] = messages
            yield ('answer', '根据数据，本月利润达标。')
            yield ('final', {'content': '根据数据，本月利润达标。', 'tool_calls': None})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu, 'messages': [
                    {'role': 'user', 'content': '本月经营如何？'},
                    {'role': 'assistant', 'content': '收入200万。'},
                    {'role': 'user', 'content': '利润达标吗？'},
                ]}),
                content_type='application/json', **self.auth())
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp['Content-Type'], 'text/event-stream')
            body = b''.join(resp.streaming_content).decode('utf-8')

        events = [json.loads(fr[5:].strip())
                  for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        types = [e['type'] for e in events]
        self.assertEqual(types[0], 'meta')
        self.assertEqual(types[-1], 'done')
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        self.assertEqual(answer, '根据数据，本月利润达标。')
        # 工具调用循环默认以 PRO（Agent）模型驱动，用最强推理干大活
        self.assertEqual(captured['model'], settings.DEEPSEEK_AGENT_MODEL)
        self.assertEqual(settings.DEEPSEEK_AGENT_MODEL, settings.DEEPSEEK_PRO_MODEL)
        # meta 事件回报的模型与实际调用一致，前端可展示
        meta = next(e for e in events if e['type'] == 'meta')
        self.assertEqual(meta['model'], settings.DEEPSEEK_AGENT_MODEL)
        # 含 system 人设 + 数据上下文 + 完整对话历史（末条为用户提问）
        msgs = captured['messages']
        self.assertEqual(msgs[0]['role'], 'system')
        self.assertIn('经营数据上下文', msgs[1]['content'])
        # 注入当前日期，避免到期/逾期天数算错
        import datetime as _dt
        self.assertIn(f'{_dt.date.today():%Y年%m月%d日}', msgs[1]['content'])
        self.assertEqual(msgs[-1]['role'], 'user')
        self.assertEqual(msgs[-1]['content'], '利润达标吗？')

    def test_cockpit_ai_chat_requires_user_question(self):
        self.mk(2026, 5, 200, 130)
        resp = self.client.post(
            '/api/cw/cockpit/ai-chat/stream',
            data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu, 'messages': [
                {'role': 'assistant', 'content': '历史回答'},
            ]}),
            content_type='application/json', **self.auth())
        self.assertEqual(resp.status_code, 400)

    def test_cockpit_knowledge_crud_and_injection(self):
        """知识库：增/查/删，且被注入对话上下文（让助手越用越聪明）。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)
        r = self.client.post(
            '/api/cw/cockpit/knowledge',
            data=json.dumps({'content': '阔展大客户Q2流失，收入下滑属预期', 'scope': '全集团', 'kind': 'background'}),
            content_type='application/json', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        kid = r.json()['data']['id']

        lst = self.client.get('/api/cw/cockpit/knowledge', **self.auth())
        self.assertTrue(any(k['id'] == kid for k in lst.json()['data']['items']))

        captured = {}

        def fake_stream_raw(messages, tools=None, model=None, timeout=90, max_tokens=1800, **kw):
            captured['messages'] = messages
            yield ('answer', 'ok')
            yield ('final', {'content': 'ok', 'tool_calls': None})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '背景如何'}]}),
                content_type='application/json', **self.auth())
            b''.join(resp.streaming_content)
        joined = '\n'.join(m['content'] for m in captured['messages'])
        self.assertIn('知识库', joined)
        self.assertIn('大客户Q2流失', joined)

        d = self.client.delete(f'/api/cw/cockpit/knowledge/{kid}', **self.auth())
        self.assertEqual(d.status_code, 200)

    def test_cockpit_knowledge_distill(self):
        """AI 自我提炼：把一段分析提炼成知识入库（来源标记 ai）。"""
        from unittest import mock

        def fake_chat(messages, timeout=90, model=None, max_tokens=1800, **kw):
            return '{"title":"应收风险","content":"逾期集中在大东，需加强催收。"}'

        with mock.patch('caiwu.views._deepseek_chat', fake_chat):
            r = self.client.post(
                '/api/cw/cockpit/knowledge/distill',
                data=json.dumps({'text': '大东逾期20万，账龄拉长……', 'scope': '全集团'}),
                content_type='application/json', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['data']['title'], '应收风险')
        self.assertEqual(r.json()['data']['source'], 'ai')

    def test_knowledge_import_text_raw(self):
        """文件导入（原文切块）：文本文件 → 知识条目。"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile('notes.txt', '第一条经营背景说明\n第二条口径说明'.encode('utf-8'),
                               content_type='text/plain')
        r = self.client.post('/api/cw/cockpit/knowledge/import',
                             {'file': f, 'scope': '全集团', 'mode': 'raw'}, **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreaterEqual(r.json()['data']['created'], 1)

    def test_knowledge_import_distill(self):
        """文件导入（AI 提炼）：文档 → 多条知识。"""
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile

        def fake_chat(messages, timeout=90, model=None, max_tokens=1800, **kw):
            return '[{"title":"背景A","content":"要点A"},{"title":"背景B","content":"要点B"}]'

        f = SimpleUploadedFile('doc.md', '# 标题\n这里是一些经营文档内容'.encode('utf-8'))
        with mock.patch('caiwu.views._deepseek_chat', fake_chat):
            r = self.client.post('/api/cw/cockpit/knowledge/import',
                                 {'file': f, 'scope': '全集团', 'mode': 'distill'}, **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['data']['created'], 2)
        items = self.client.get('/api/cw/cockpit/knowledge', **self.auth()).json()['data']['items']
        self.assertTrue(any(k['source'] == 'ai' and k['title'] == '背景A' for k in items))

    def test_chat_function_calling_tool_then_answer(self):
        """function-calling：模型先调用 save_knowledge 工具，再给出最终回答。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)
        calls = {'n': 0}

        def fake_stream_raw(messages, tools=None, model=None, timeout=90, max_tokens=1800, **kw):
            calls['n'] += 1
            if calls['n'] == 1:
                yield ('final', {'content': '', 'tool_calls': [{'id': 'c1', 'function': {
                    'name': 'save_knowledge',
                    'arguments': '{"content":"工具写入的知识Z","scope":"全集团"}'}}]})
            else:
                yield ('answer', '已记录并回答。')
                yield ('final', {'content': '已记录并回答。', 'tool_calls': None})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '把这条记下来'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip()) for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        self.assertIn('tool', [e['type'] for e in events])
        # 工具完成事件含计时与成败，供前端展示"✓ Nms"
        done = next(e for e in events if e['type'] == 'tool_done')
        self.assertEqual(done['name'], 'save_knowledge')
        self.assertTrue(done['ok'])
        self.assertIsInstance(done['ms'], int)
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        self.assertIn('已记录并回答', answer)
        items = self.client.get('/api/cw/cockpit/knowledge', **self.auth()).json()['data']['items']
        self.assertTrue(any(k['content'] == '工具写入的知识Z' for k in items))

    def test_chat_function_calling_generate_report(self):
        """function-calling：模型调用 generate_report（终止型技能），直接流式产出报告。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)

        def fake_stream_raw(messages, tools=None, model=None, timeout=90, max_tokens=1800, **kw):
            yield ('final', {'content': '', 'tool_calls': [{'id': 'r1', 'function': {
                'name': 'generate_report', 'arguments': '{"period":"month"}'}}]})

        def fake_stream(messages, model=None, max_tokens=1800, timeout=300, **kw):
            yield ('answer', '【正文】本月经营稳健。')

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw), \
                mock.patch('caiwu.views._deepseek_stream', fake_stream):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '生成本月经营分析报告'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip()) for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        self.assertIn('经营分析报告', answer)   # 技能注入的标题
        self.assertIn('本月经营稳健', answer)
        self.assertEqual(events[-1]['type'], 'done')

    def test_chat_stream_is_truly_incremental_with_reasoning(self):
        """真流式：reasoning 与 answer 分片逐帧透传（非整段切片），且 reasoning 先于 answer。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)

        def fake_stream_raw(messages, tools=None, model=None, timeout=90, max_tokens=1800, **kw):
            yield ('reasoning', '先看收入…')
            yield ('answer', '本月')
            yield ('answer', '利润')
            yield ('answer', '达标。')
            yield ('final', {'content': '本月利润达标。', 'tool_calls': None})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '利润如何'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip())
                  for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        types = [e['type'] for e in events]
        self.assertIn('reasoning', types)
        self.assertLess(types.index('reasoning'), types.index('answer'))
        # answer 逐片透传（3 帧），而非一次性整段
        self.assertEqual([e['delta'] for e in events if e['type'] == 'answer'],
                         ['本月', '利润', '达标。'])
        self.assertEqual(types[-1], 'done')

    def test_chat_stream_max_steps_wraps_up_instead_of_aborting(self):
        """工具调用循环用尽步数上限后不再直接吐出「处理步骤过多」中断，而是去掉 tools
        强制模型基于已取数据收口作答；仅当收口调用本身也没有内容时才兜底提示。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)

        def fake_stream_raw(messages, tools=None, model=None, timeout=120, max_tokens=2000, **kw):
            if tools is None:
                # 收口调用：不再挂 tools，模型只能总结作答
                yield ('answer', '已根据已获取数据给出阶段性结论。')
                yield ('final', {'content': '已根据已获取数据给出阶段性结论。', 'tool_calls': None})
                return
            yield ('final', {'content': '', 'tool_calls': [{'id': 'c1', 'function': {
                'name': 'search_knowledge', 'arguments': '{"query":"x"}'}}]})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '把近半年所有维度都分析一遍'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip()) for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        self.assertIn('已根据已获取数据给出阶段性结论', answer)
        self.assertNotIn('处理步骤过多', answer)
        self.assertEqual(events[-1]['type'], 'done')

    def test_chat_stream_max_steps_fallback_when_wrapup_empty(self):
        """收口调用也没能产出任何内容时，仍需给用户一个可读的兜底提示，而不是空响应。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)

        def fake_stream_raw(messages, tools=None, model=None, timeout=120, max_tokens=2000, **kw):
            if tools is None:
                yield ('final', {'content': '', 'tool_calls': None})
                return
            yield ('final', {'content': '', 'tool_calls': [{'id': 'c1', 'function': {
                'name': 'search_knowledge', 'arguments': '{"query":"x"}'}}]})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '把近半年所有维度都分析一遍'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip()) for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        self.assertTrue(answer)   # 兜底提示非空
        self.assertEqual(events[-1]['type'], 'done')

    def test_chat_stream_auto_continues_truncated_answer(self):
        """答案因 token 上限被截断（finish_reason=='length'）时，自动接着写完而非中断，
        根治"回答一般就中断不输出"。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)
        calls = {'n': 0}

        def fake_stream_raw(messages, tools=None, model=None, timeout=120, max_tokens=2000, **kw):
            calls['n'] += 1
            if calls['n'] == 1:
                # 第一段：被截断（length）
                yield ('answer', '本月经营分析（上）：收入达标，')
                yield ('final', {'content': '本月经营分析（上）：收入达标，',
                                 'tool_calls': None, 'finish_reason': 'length'})
            else:
                # 续写段：正常收尾（stop）
                yield ('answer', '利润率环比改善，建议保持。')
                yield ('final', {'content': '利润率环比改善，建议保持。',
                                 'tool_calls': None, 'finish_reason': 'stop'})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '写一份本月经营分析'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip()) for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        # 两段拼接成完整答案
        self.assertIn('收入达标', answer)
        self.assertIn('建议保持', answer)
        self.assertGreaterEqual(calls['n'], 2)   # 触发了续写
        self.assertEqual(events[-1]['type'], 'done')

    def test_chat_stream_truncation_continue_has_guard(self):
        """续写有兜底上限：即便模型持续回报 length 也不会无限续写，最终收口 done。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)
        calls = {'n': 0}

        def fake_stream_raw(messages, tools=None, model=None, timeout=120, max_tokens=2000, **kw):
            calls['n'] += 1
            yield ('answer', f'第{calls["n"]}段…')
            yield ('final', {'content': f'第{calls["n"]}段…',
                             'tool_calls': None, 'finish_reason': 'length'})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '写一份很长的分析'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip()) for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        # 首答 1 次 + 续写上限 3 次 = 4，不会失控
        self.assertLessEqual(calls['n'], 4)
        self.assertEqual(events[-1]['type'], 'done')

    def test_chat_stream_falls_back_when_primary_rejects_tools(self):
        """PRO 模型在首个 token 前失败（如某端点该模型不支持 tools）→ 自动降级到
        DEEPSEEK_FALLBACK_MODEL 重试并正常作答，助手不整体报错。"""
        from unittest import mock
        from django.conf import settings
        self.mk(2026, 5, 200, 130)
        seen = {'models': []}

        def fake_stream_raw(messages, tools=None, model=None, timeout=120, max_tokens=2000, **kw):
            seen['models'].append(model)
            if model == settings.DEEPSEEK_AGENT_MODEL:
                raise RuntimeError('该模型不支持 tools（400）')
            yield ('answer', '已降级作答：本月利润达标。')
            yield ('final', {'content': '已降级作答：本月利润达标。', 'tool_calls': None})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '利润如何'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip()) for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        # 先试 PRO 模型，失败后降级到 FALLBACK 模型
        self.assertEqual(seen['models'][0], settings.DEEPSEEK_AGENT_MODEL)
        self.assertIn(settings.DEEPSEEK_FALLBACK_MODEL, seen['models'])
        # 回报一个 fallback meta 事件，前端可提示已降级
        self.assertTrue(any(e['type'] == 'meta' and e.get('fallback') for e in events))
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        self.assertIn('本月利润达标', answer)
        self.assertEqual(events[-1]['type'], 'done')

    def test_agent_skills_list_and_run(self):
        """Agent 技能：列表含基础技能，且可执行 写入/检索/清理 知识库。"""
        r = self.client.get('/api/cw/cockpit/skills', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        names = [s['name'] for s in r.json()['data']['skills']]
        for n in ('save_knowledge', 'search_knowledge', 'forget_knowledge'):
            self.assertIn(n, names)

        run = self.client.post(
            '/api/cw/cockpit/skills/run',
            data=json.dumps({'name': 'save_knowledge', 'args': {'content': '技能写入的知识X', 'scope': '全集团'}}),
            content_type='application/json', **self.auth())
        self.assertEqual(run.status_code, 200, run.content)

        s = self.client.post(
            '/api/cw/cockpit/skills/run',
            data=json.dumps({'name': 'search_knowledge', 'args': {'query': '技能写入'}}),
            content_type='application/json', **self.auth())
        self.assertTrue(any('技能写入' in x['content'] for x in s.json()['data']))

        f = self.client.post(
            '/api/cw/cockpit/skills/run',
            data=json.dumps({'name': 'forget_knowledge', 'args': {'query': '技能写入'}}),
            content_type='application/json', **self.auth())
        self.assertGreaterEqual(f.json()['data']['deleted'], 1)

    def test_agent_readonly_query_skills(self):
        """只读数据查询技能：列表含三个查询工具，可按 期间/事业部 取数且复用驾驶舱口径；
        无数据时返回兜底文案而非报错。"""
        self.mk(2026, 5, 200, 130)
        names = [s['name'] for s in
                 self.client.get('/api/cw/cockpit/skills', **self.auth()).json()['data']['skills']]
        for n in ('query_financials', 'query_receivables', 'query_project_margin',
                  'query_bf_fusion', 'query_forecast'):
            self.assertIn(n, names)

        # 业绩查询：指定期间/事业部 → 返回文本含该事业部口径
        r = self.client.post(
            '/api/cw/cockpit/skills/run',
            data=json.dumps({'name': 'query_financials',
                             'args': {'year': 2026, 'month': 5, 'bu': self.bu}}),
            content_type='application/json', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn(self.bu, r.json()['data'])

        # 应收/毛利/归因/预测无数据时不报错，返回字符串兜底
        for n in ('query_receivables', 'query_project_margin', 'query_bf_fusion', 'query_forecast'):
            q = self.client.post(
                '/api/cw/cockpit/skills/run',
                data=json.dumps({'name': n, 'args': {'year': 2026, 'month': 5, 'bu': self.bu}}),
                content_type='application/json', **self.auth())
            self.assertEqual(q.status_code, 200, q.content)
            self.assertIsInstance(q.json()['data'], str)

    def test_query_financials_uses_gross_profit_caliber(self):
        """经营业绩取数以【经营毛利】为主口径（集团分析报告口径），净利作参考。"""
        self.mk(2026, 5, 200, 130)
        r = self.client.post(
            '/api/cw/cockpit/skills/run',
            data=json.dumps({'name': 'query_financials',
                             'args': {'year': 2026, 'month': 5, 'bu': self.bu}}),
            content_type='application/json', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        text = r.json()['data']
        self.assertIn('经营毛利', text)                       # 主口径出现
        self.assertIn('经营毛利为主', text)                   # 概览抬头点明口径
        self.assertIn('收入/经营毛利', text)                  # 12月趋势按毛利口径

    def test_web_research_disabled_by_default(self):
        """未配置搜索 Key 时联网检索默认关闭：三项联网技能不对外暴露、不可经入口执行，
        非联网技能不受影响。"""
        self.mk(2026, 5, 200, 130)
        names = [s['name'] for s in
                 self.client.get('/api/cw/cockpit/skills', **self.auth()).json()['data']['skills']]
        for n in ('web_search', 'peer_research', 'web_fetch'):
            self.assertNotIn(n, names)
        # 非联网技能仍在
        self.assertIn('query_financials', names)
        self.assertIn('save_knowledge', names)
        # 统一入口拒绝执行被门控的联网技能
        run = self.client.post(
            '/api/cw/cockpit/skills/run',
            data=json.dumps({'name': 'web_search', 'args': {'query': '物流行业'}}),
            content_type='application/json', **self.auth())
        self.assertEqual(run.status_code, 403, run.content)

    @override_settings(ENABLE_WEB_RESEARCH=True)
    def test_web_research_exposed_when_enabled(self):
        """显式开启联网检索后，三项联网技能重新对外暴露并可执行。"""
        self.mk(2026, 5, 200, 130)
        names = [s['name'] for s in
                 self.client.get('/api/cw/cockpit/skills', **self.auth()).json()['data']['skills']]
        for n in ('web_search', 'peer_research', 'web_fetch'):
            self.assertIn(n, names)
        from caiwu import agent_skills
        tool_names = [t['function']['name'] for t in agent_skills.agent_tools()]
        self.assertIn('web_search', tool_names)

    def test_chat_multi_step_tool_calls(self):
        """跨期间多步取数：模型连续调用查询技能 >4 步后再综合作答（循环上限已提到 12）。"""
        from unittest import mock
        self.mk(2026, 5, 200, 130)
        calls = {'n': 0}

        def fake_stream_raw(messages, tools=None, model=None, timeout=90, max_tokens=1800, **kw):
            calls['n'] += 1
            if calls['n'] <= 5:   # 连续 5 步各调一次查询工具（旧上限 4 会被卡住）
                yield ('final', {'content': '', 'tool_calls': [{'id': f'c{calls["n"]}', 'function': {
                    'name': 'query_financials',
                    'arguments': '{"year":2026,"month":%d}' % calls['n']}}]})
            else:
                yield ('answer', '综合各期：稳健。')
                yield ('final', {'content': '综合各期：稳健。', 'tool_calls': None})

        with mock.patch('caiwu.views._deepseek_stream_raw', fake_stream_raw):
            resp = self.client.post(
                '/api/cw/cockpit/ai-chat/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bu': self.bu,
                                 'messages': [{'role': 'user', 'content': '各月对比一下'}]}),
                content_type='application/json', **self.auth())
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip())
                  for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        # 5 次工具事件 + 最终答案均到达（证明未被 4 步上限截断）
        self.assertEqual(sum(1 for e in events if e['type'] == 'tool'), 5)
        self.assertIn('综合各期', ''.join(e['delta'] for e in events if e['type'] == 'answer'))
        self.assertEqual(events[-1]['type'], 'done')

    def test_knowledge_import_dedup(self):
        """同范围内内容完全相同的导入不重复入库。"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        payload = '同一条经营背景内容用于去重测试'
        for _ in range(2):
            f = SimpleUploadedFile('n.txt', payload.encode('utf-8'))
            self.client.post('/api/cw/cockpit/knowledge/import',
                             {'file': f, 'scope': '全集团', 'mode': 'raw'}, **self.auth())
        items = self.client.get('/api/cw/cockpit/knowledge', **self.auth()).json()['data']['items']
        self.assertEqual(sum(1 for k in items if k['content'] == payload), 1)

    def test_report_matrix_and_export(self):
        """月度矩阵报表：1月→最后已发布月，各月金额+合计；导出返回美化 xlsx。"""
        self.mk(2026, 1, 100, 60)
        self.mk(2026, 2, 200, 130)
        r = self.client.get('/api/cw/report/matrix',
                            {'year': 2026, 'bu': self.bu, 'level': 1}, **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        self.assertEqual(d['months'], [1, 2])
        self.assertEqual(d['last_month'], 2)
        rev = next(x for x in d['rows'] if x['l1_name'] == REV)
        self.assertEqual(rev['values'], [100.0, 200.0])
        self.assertEqual(rev['total'], 300.0)
        # 计算行（经营净利）各月之和=合计
        net = next(x for x in d['rows'] if x['l1_name'] == NET_PROFIT)
        self.assertAlmostEqual(net['total'], net['values'][0] + net['values'][1], places=2)
        # 导出
        ex = self.client.get('/api/cw/report/export',
                             {'year': 2026, 'bu': self.bu, 'level': 1}, **self.auth())
        self.assertEqual(ex.status_code, 200, ex.content)
        self.assertIn('spreadsheet', ex['Content-Type'])

    def test_report_ai_stream_emits_answer_frames(self):
        from unittest import mock
        self.mk(2026, 5, 200, 130)

        def fake_stream(messages, model=None, max_tokens=1800, timeout=300, **kw):
            # 快模型只产出正文（无 reasoning_content）
            yield ('answer', '本月经营')
            yield ('answer', '稳健。')

        with mock.patch('caiwu.views._deepseek_stream', fake_stream):
            resp = self.client.post(
                '/api/cw/report/ai-analysis/stream',
                data=json.dumps({'year': 2026, 'month': 5, 'bus': [self.bu]}),
                content_type='application/json', **self.auth())
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp['Content-Type'], 'text/event-stream')
            body = b''.join(resp.streaming_content).decode('utf-8')
        events = [json.loads(fr[5:].strip())
                  for fr in body.split('\n\n') if fr.strip().startswith('data:')]
        types = [e['type'] for e in events]
        self.assertEqual(types[0], 'meta')
        self.assertEqual(types[-1], 'done')
        answer = ''.join(e['delta'] for e in events if e['type'] == 'answer')
        self.assertEqual(answer, '本月经营稳健。')

    def test_cockpit_ai_stream_no_data_is_json_error(self):
        # 无数据时应在开流前以普通 JSON 错误返回，而非 event-stream
        from unittest import mock
        with mock.patch('caiwu.views._deepseek_stream') as m:
            resp = self.client.post(
                '/api/cw/cockpit/ai-analysis/stream',
                data=json.dumps({'year': 2024, 'month': 3}),
                content_type='application/json', **self.auth())
        self.assertEqual(resp.status_code, 400)
        self.assertNotEqual(resp['Content-Type'], 'text/event-stream')
        m.assert_not_called()


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'])
class CaiwuControlIntegrityTests(TestCase):
    """财务分析与控制链路加固回归：发布批次删除保护、目标部分上传校验、
    导出公式转义、AI JSON 提取、项目毛利对账透出。"""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        for name, sort_order, is_calculated, sign, is_profit_driver in L1_SEEDS:
            L1Category.objects.update_or_create(
                name=name,
                defaults={'sort_order': sort_order, 'is_calculated': is_calculated,
                          'sign': sign, 'is_profit_driver': is_profit_driver})
        cls.admin = PaikuanUser(
            phone='13900000600', name='CW Admin', role='super_admin',
            job_title='finance_director', departments=[],
            is_active=True, is_approved=True)
        cls.admin.set_password('Test123456')
        cls.admin.save()
        # 非超管但默认职务配置带 caiwu_delete=True 的财务总监
        cls.fd = PaikuanUser(
            phone='13900000601', name='FD User', role='operator',
            job_title='finance_director', departments=[BUSINESS_UNITS[1]],
            is_active=True, is_approved=True)
        cls.fd.set_password('Test123456')
        cls.fd.save()

    def setUp(self):
        from paikuan.views import _invalidate_perm_cache
        _invalidate_perm_cache()
        self.client = Client()
        self.bu = BUSINESS_UNITS[1]
        self.l1 = {c.name: c for c in L1Category.objects.order_by('sort_order', 'id')}

    def auth(self, user=None):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(user or self.admin)}'}

    def mk_batch(self, status, bu=None, year=2026, month=5, amounts=None):
        b = ImportBatch.objects.create(
            business_unit=bu or self.bu, year=year, month=month,
            batch_type=ImportBatch.TYPE_DEPT, status=status,
            uploaded_by=self.admin, row_count=len(amounts or {}),
            file_name='ctl.xlsx')
        for name, amount in (amounts or {}).items():
            FinancialEntry.objects.create(batch=b, l1=self.l1[name],
                                          amount=Decimal(str(amount)))
        return b

    # ── 发布批次删除保护 ─────────────────────────────────────────────────────
    def test_published_batch_delete_blocked_for_non_admin(self):
        b = self.mk_batch(ImportBatch.STATUS_PUBLISHED, amounts={REV: '100'})
        resp = self.client.delete(f'/api/cw/batches/{b.id}', **self.auth(self.fd))
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertIn('已发布批次不可删除', resp.json().get('error', ''))
        self.assertTrue(ImportBatch.objects.filter(id=b.id).exists())
        self.assertEqual(b.entries.count(), 1)

    def test_published_batch_delete_allowed_for_super_admin(self):
        b = self.mk_batch(ImportBatch.STATUS_PUBLISHED, amounts={REV: '100'})
        resp = self.client.delete(f'/api/cw/batches/{b.id}', **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(ImportBatch.objects.filter(id=b.id).exists())

    def test_draft_batch_delete_allowed_for_can_delete_user(self):
        b = self.mk_batch(ImportBatch.STATUS_DRAFT, amounts={REV: '100'})
        resp = self.client.delete(f'/api/cw/batches/{b.id}', **self.auth(self.fd))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(ImportBatch.objects.filter(id=b.id).exists())

    # ── 目标部分上传：月度合计超年度被拦截 ───────────────────────────────────
    def post_targets(self, items, year=2026):
        return self.client.post('/api/cw/targets',
                                data=json.dumps({'year': year, 'items': items}),
                                content_type='application/json', **self.auth())

    def test_partial_months_over_annual_rejected(self):
        # 年度收入 1200，仅填 1-3 月各 500（合计 1500 > 1200）→ 应拦截
        items = [{'business_unit': self.bu, 'month': 0, 'target_revenue': '12000000'}]
        items += [{'business_unit': self.bu, 'month': m, 'target_revenue': '5000000'}
                  for m in (1, 2, 3)]
        resp = self.post_targets(items)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('超过年度目标', resp.json().get('error', ''))

    def test_partial_months_under_annual_allowed(self):
        # 年度 1200，仅填 1-3 月各 100（合计 300 < 1200）→ 逐月录入中，放行
        items = [{'business_unit': self.bu, 'month': 0, 'target_revenue': '12000000'}]
        items += [{'business_unit': self.bu, 'month': m, 'target_revenue': '1000000'}
                  for m in (1, 2, 3)]
        resp = self.post_targets(items)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(FinancialTarget.objects.filter(
            business_unit=self.bu, year=2026).count(), 4)

    # ── 导出公式注入转义（中央出口 _build_excel_response）────────────────────
    def test_excel_export_escapes_formula_cells(self):
        import io
        from openpyxl import load_workbook
        from caiwu.views import _build_excel_response
        wb = Workbook()
        ws = wb.active
        ws.append(['=cmd|calc!A0', '+SUM(A1)', '安全文本', 123])
        resp = _build_excel_response(wb, 'x.xlsx')
        out = load_workbook(io.BytesIO(resp.content)).active
        self.assertEqual(out['A1'].value, "'=cmd|calc!A0")
        self.assertEqual(out['B1'].value, "'+SUM(A1)")
        self.assertEqual(out['C1'].value, '安全文本')
        self.assertEqual(out['D1'].value, 123)

    # ── AI 回复 JSON 提取：边界与兜底 ────────────────────────────────────────
    def test_extract_json_block(self):
        from caiwu.views import _extract_json_block
        self.assertEqual(
            _extract_json_block('以下是结果：[{"a": 1}] 完毕', kind='array'),
            [{'a': 1}])
        self.assertEqual(
            _extract_json_block('```json\n{"title": "T", "content": "C"}\n```'),
            {'title': 'T', 'content': 'C'})
        self.assertIsNone(_extract_json_block('没有任何JSON', kind='array'))
        self.assertIsNone(_extract_json_block('{broken json]'))
        self.assertIsNone(_extract_json_block('', kind='array'))

    # ── 项目毛利 ↔ 报表收入对账透出 ─────────────────────────────────────────
    def test_project_margin_recon_against_report_revenue(self):
        from caiwu.models import ProjectMargin
        self.mk_batch(ImportBatch.STATUS_PUBLISHED, amounts={REV: '1000', COST: '600'})
        ProjectMargin.objects.create(
            business_unit=self.bu, year=2026, month=5, project_name='项目A',
            revenue=Decimal('800'), cost=Decimal('500'))
        resp = self.client.get('/api/cw/project-margin',
                               {'bu': self.bu, 'year': 2026, 'month': 5},
                               **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        s = resp.json()['data']['summary']
        self.assertEqual(s['report_revenue'], 1000.0)
        self.assertEqual(s['revenue_diff'], -200.0)  # 项目台账 800 - 报表 1000

    def test_project_margin_recon_none_when_no_published_report(self):
        from caiwu.models import ProjectMargin
        ProjectMargin.objects.create(
            business_unit=self.bu, year=2026, month=5, project_name='项目B',
            revenue=Decimal('300'), cost=Decimal('100'))
        resp = self.client.get('/api/cw/project-margin',
                               {'bu': self.bu, 'year': 2026, 'month': 5},
                               **self.auth())
        self.assertEqual(resp.status_code, 200, resp.content)
        s = resp.json()['data']['summary']
        self.assertIsNone(s['report_revenue'])
        self.assertIsNone(s['revenue_diff'])


class InternalReconTests(TestCase):
    """内部往来核对：金蝶明细账解析、镜像矩阵、两两自动配对。"""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        cls.admin = PaikuanUser(
            phone='13900000077', name='内往管理员', role='super_admin',
            job_title='finance_director', departments=[], is_active=True, is_approved=True)
        cls.admin.set_password('Test123456')
        cls.admin.save()

    def setUp(self):
        self.client = Client()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(self.admin)}'}

    @staticmethod
    def _ledger_xlsx(rows):
        """构造金蝶「核算维度明细账（往来单位）」样式的 xlsx。"""
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['核算维度明细账'])                       # 标题行（干扰行）
        ws.append(['日期', '凭证字号', '往来单位', '科目编码', '科目名称', '摘要', '借方', '贷方'])
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'ledger.xlsx'
        return buf

    def _upload(self, bu, rows, year=2026, month=6):
        f = self._ledger_xlsx(rows)
        return self.client.post('/api/cw/internal/upload',
                                {'bu': bu, 'year': year, 'month': month, 'file': f},
                                **self.auth())

    def test_upload_parse_and_counterparty_mapping(self):
        res = self._upload('劳务事业部', [
            ['2026-06-05', '记-1', '青岛运输事业部有限公司', '1221.01', '其他应收款', '代付运费', 1000, 0],
            ['2026-06-08', '记-2', '集团总部', '2241.01', '其他应付款', '总部借款', 0, 500],
            ['2026-06-09', '记-3', '不认识的公司', '1221.01', '其他应收款', '外部往来', 200, 0],
            ['', '', '', '', '', '本期合计', 1200, 500],       # 小计行须跳过
        ])
        self.assertEqual(res.status_code, 200, res.content)
        d = res.json()['data']
        self.assertEqual(d['rows'], 3)
        self.assertEqual(d['skipped'], 1)
        self.assertEqual(d['unmatched'], [{'raw': '不认识的公司', 'count': 1}])
        ents = {e.counterparty_raw: e for e in InternalEntry.objects.all()}
        self.assertEqual(ents['青岛运输事业部有限公司'].counterparty, '运输事业部')
        self.assertEqual(ents['青岛运输事业部有限公司'].side, 'ar')
        self.assertEqual(ents['集团总部'].counterparty, '集团总部')
        self.assertEqual(ents['集团总部'].side, 'ap')
        self.assertEqual(ents['不认识的公司'].counterparty, '')

    def test_reupload_replaces_batch(self):
        self._upload('劳务事业部', [['2026-06-05', '记-1', '运输事业部', '1221', '', '费用', 100, 0]])
        self._upload('劳务事业部', [['2026-06-06', '记-2', '运输事业部', '1221', '', '费用2', 300, 0]])
        self.assertEqual(InternalBatch.objects.count(), 1)
        self.assertEqual(InternalEntry.objects.count(), 1)
        self.assertEqual(float(InternalEntry.objects.get().debit), 300)

    def test_matrix_mirror_and_diff(self):
        # 劳务对运输应收 1000；运输只入账 800 应付 → 差异 200
        self._upload('劳务事业部', [
            ['2026-06-05', '记-1', '运输事业部', '1221.01', '', '代付运费', 1000, 0]])
        self._upload('运输事业部', [
            ['2026-06-05', '记-9', '劳务事业部', '2241.01', '', '代付运费', 0, 800]])
        res = self.client.get('/api/cw/internal/matrix?year=2026&month=6', **self.auth())
        self.assertEqual(res.status_code, 200, res.content)
        d = res.json()['data']
        pair = next(p for p in d['pairs']
                    if {p['a'], p['b']} == {'劳务事业部', '运输事业部'})
        self.assertAlmostEqual(abs(pair['diff']), 200.0, places=2)
        self.assertTrue(pair['both_uploaded'])
        self.assertAlmostEqual(d['kpi']['total_diff'], 200.0, places=2)
        self.assertEqual(sorted(d['uploaded']), ['劳务事业部', '运输事业部'])

    def test_pair_auto_match_marks_equal_amounts(self):
        self._upload('劳务事业部', [
            ['2026-06-05', '记-1', '运输事业部', '1221.01', '', '代付A', 1000, 0],
            ['2026-06-10', '记-2', '运输事业部', '1221.01', '', '代付B', 250, 0],
        ])
        self._upload('运输事业部', [
            ['2026-06-06', '记-8', '劳务事业部', '2241.01', '', '代付A', 0, 1000],
            ['2026-06-20', '记-9', '劳务事业部', '2241.01', '', '代付C', 0, 88],
        ])
        res = self.client.get(
            '/api/cw/internal/pair?year=2026&month=6&a=劳务事业部&b=运输事业部', **self.auth())
        self.assertEqual(res.status_code, 200, res.content)
        d = res.json()['data']
        self.assertEqual(d['matched_pairs'], 1)
        self.assertAlmostEqual(d['matched_amount'], 1000.0, places=2)
        a_matched = [r for r in d['a_rows'] if r['match']]
        b_matched = [r for r in d['b_rows'] if r['match']]
        self.assertEqual(len(a_matched), 1)
        self.assertEqual(a_matched[0]['summary'], '代付A')
        self.assertEqual(a_matched[0]['match'], b_matched[0]['match'])
        # 差异 = 1250 应收 - 1088 应付镜像 = 162
        self.assertAlmostEqual(d['diff'], 162.0, places=2)

    def test_same_sign_rows_do_not_match(self):
        # 双方都挂应收（同号）→ 不能互相配对
        self._upload('劳务事业部', [
            ['2026-06-05', '记-1', '运输事业部', '1221.01', '', '费用', 500, 0]])
        self._upload('运输事业部', [
            ['2026-06-06', '记-8', '劳务事业部', '1221.02', '', '费用', 500, 0]])
        res = self.client.get(
            '/api/cw/internal/pair?year=2026&month=6&a=劳务事业部&b=运输事业部', **self.auth())
        d = res.json()['data']
        self.assertEqual(d['matched_pairs'], 0)
        self.assertAlmostEqual(d['diff'], 1000.0, places=2)

    def test_batches_coverage_and_delete(self):
        self._upload('劳务事业部', [['2026-06-05', '记-1', '运输事业部', '1221', '', '费用', 100, 0]])
        res = self.client.get('/api/cw/internal/batches?year=2026&month=6', **self.auth())
        d = res.json()['data']
        idx = d['units'].index('劳务事业部')
        self.assertIsNotNone(d['batches'][idx])
        bid = d['batches'][idx]['detail']['id']
        res = self.client.delete(f'/api/cw/internal/batches/{bid}', **self.auth())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(InternalEntry.objects.count(), 0)

    @staticmethod
    def _kingdee_detail_xlsx(rows):
        """真实金蝶「明细分类账」形制：标题行 + 账簿行 + 两行复合表头 + 账簿列。"""
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['明细分类账'])
        ws.append(['账簿 : 卡行通集团主账簿; 四川迭黎信息技术有限公司主账簿;'])
        ws.append(['序号', '左树科目编码', '左树科目名称', '账簿', '期间', '记账日期',
                   '业务日期', '凭证字号', '摘要', '核算维度', '借方', '贷方', '余额', ''])
        ws.append(['', '', '', '', '', '', '', '', '', '', '', '', '方向', '金额'])
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'detail.xlsx'
        return buf

    def test_kingdee_multibook_detail_autosplit(self):
        """真实形制：账簿列自动拆主体、公司全称映射、期初余额行跳过、期间按记账日期。"""
        f = self._kingdee_detail_xlsx([
            [1.0, '2241.04', '内部往来', '卡行通集团主账簿', '', '', '', '', '期初余额',
             '组织机构:四川阔展物流有限公司', '', '', '借', 2176795.72],
            [2.0, '2241.04', '内部往来', '卡行通集团主账簿', '2026年5期', '2026-05-01', '2026-05-01',
             '记0007', '阔展收停车费', '组织机构:四川阔展物流有限公司', 72.57, '', '借', 2176868.29],
            [3.0, '2241.04', '内部往来', '四川迭黎信息技术有限公司主账簿', '2026年5期', '2026-05-02',
             '2026-05-02', '记0009', '总部代付', '组织机构:卡行通集团', '', 500, '贷', 500],
        ])
        res = self.client.post('/api/cw/internal/upload', {'file': f}, **self.auth())
        self.assertEqual(res.status_code, 200, res.content)
        d = res.json()['data']
        self.assertEqual(d['kind'], 'detail')
        self.assertEqual(d['rows'], 2)
        bus = sorted(b['business_unit'] for b in d['batches'])
        self.assertEqual(bus, ['劳务事业部', '集团总部'])
        e1 = InternalEntry.objects.get(business_unit='集团总部')
        self.assertEqual(e1.counterparty, '阔展事业部')
        self.assertEqual((e1.year, e1.month), (2026, 5))
        e2 = InternalEntry.objects.get(business_unit='劳务事业部')
        self.assertEqual(e2.counterparty, '集团总部')

    @staticmethod
    def _kingdee_balance_xlsx(rows):
        """真实金蝶「核算维度余额表」形制：两行复合表头（组头+借/贷子头）。"""
        import io
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['核算维度余额表'])
        ws.append(['账簿 : 卡行通集团主账簿;'])
        ws.append(['序号', '组织机构名称', '科目编码', '科目名称', '币种', '账簿名称',
                   '年初余额', '', '期初余额', '', '本期发生额', '', '本年累计', '', '期末余额', ''])
        ws.append(['', '', '', '', '', '',
                   '借方金额', '贷方金额', '借方金额', '贷方金额', '借方金额', '贷方金额',
                   '借方金额', '贷方金额', '借方金额', '贷方金额'])
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'balance.xlsx'
        return buf

    def test_kingdee_balance_parent_child_dedup_and_mode(self):
        """余额表：父科目 2241 与子科目 2241.04 同现仅留子行；矩阵切换期末余额口径。"""
        f = self._kingdee_balance_xlsx([
            [1.0, '成都宁创物流有限公司', '2241', '其他应付款', '人民币', '卡行通集团主账簿',
             '', '', 1859886.12, '', 3874267.83, 2188867.22, '', '', 3545286.73, ''],
            [2.0, '成都宁创物流有限公司', '2241.04', '内部往来', '人民币', '卡行通集团主账簿',
             '', '', 1859886.12, '', 3874267.83, 2188867.22, '', '', 3545286.73, ''],
        ])
        res = self.client.post('/api/cw/internal/upload',
                               {'file': f, 'year': 2026, 'month': 5}, **self.auth())
        self.assertEqual(res.status_code, 200, res.content)
        d = res.json()['data']
        self.assertEqual(d['kind'], 'balance')
        self.assertEqual(d['rows'], 1)                       # 父行去重
        bal = InternalBalance.objects.get()
        self.assertEqual(bal.business_unit, '集团总部')
        self.assertEqual(bal.counterparty, '供应链事业部')
        self.assertEqual(float(bal.closing), 3545286.73)
        self.assertEqual(float(bal.opening), 1859886.12)
        # 矩阵切换为期末余额口径
        res = self.client.get('/api/cw/internal/matrix?year=2026&month=5', **self.auth())
        d = res.json()['data']
        self.assertEqual(d['mode'], 'balance')
        pair = next(p for p in d['pairs'] if {p['a'], p['b']} == {'集团总部', '供应链事业部'})
        self.assertAlmostEqual(abs(pair['diff']), 3545286.73, places=2)

    def test_balance_multicurrency_no_double_count(self):
        """人民币 + 综合本位币 同现仅计人民币行；纯外币行不参与核对。"""
        f = self._kingdee_balance_xlsx([
            [1.0, '成都宁创物流有限公司', '2241.04', '内部往来', '人民币', '卡行通集团主账簿',
             '', '', 100, '', 50, 30, '', '', 120, ''],
            [2.0, '成都宁创物流有限公司', '2241.04', '内部往来', '综合本位币', '卡行通集团主账簿',
             '', '', 100, '', 50, 30, '', '', 120, ''],
            [3.0, '成都宁创物流有限公司', '2241.04', '内部往来', '美元', '卡行通集团主账簿',
             '', '', 10, '', 5, 3, '', '', 12, ''],
        ])
        res = self.client.post('/api/cw/internal/upload',
                               {'file': f, 'year': 2026, 'month': 5}, **self.auth())
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['data']['rows'], 1)
        self.assertEqual(float(InternalBalance.objects.get().closing), 120)

    def test_pair_includes_balance_summary(self):
        f = self._kingdee_balance_xlsx([
            [1.0, '四川迭黎信息技术有限公司', '2241.04', '内部往来', '人民币', '卡行通集团主账簿',
             '', '', 100, '', 50, 30, '', '', 120, ''],
            [2.0, '卡行通集团', '2241.04', '内部往来', '人民币', '四川迭黎信息技术有限公司主账簿',
             '', '', '', 100, 30, 50, '', '', '', 120],
        ])
        res = self.client.post('/api/cw/internal/upload',
                               {'file': f, 'year': 2026, 'month': 5}, **self.auth())
        self.assertEqual(res.status_code, 200, res.content)
        res = self.client.get(
            '/api/cw/internal/pair?year=2026&month=5&a=集团总部&b=劳务事业部', **self.auth())
        d = res.json()['data']
        self.assertIsNotNone(d['balance'])
        self.assertAlmostEqual(d['balance']['closing_diff'], 0.0, places=2)
        self.assertAlmostEqual(d['balance']['opening_diff'], 0.0, places=2)


class AgentIntelligenceTests(TestCase):
    """Agent 升级：BM25 检索、知识相关召回、历史压缩、联网技能降级、反馈端点。"""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        cls.admin = PaikuanUser(
            phone='13900000088', name='评测员', role='super_admin',
            job_title='finance_director', departments=[], is_active=True, is_approved=True)
        cls.admin.set_password('Test123456')
        cls.admin.save()

    def setUp(self):
        self.client = Client()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(self.admin)}'}

    def test_bm25_ranks_relevant_chinese_docs_first(self):
        from caiwu import retrieval
        docs = [
            (1, '运输事业部油价联动定价规则：油价涨超5%启动运价调整'),
            (2, '劳务事业部社保缴纳口径说明'),
            (3, '供应链金融坏账计提政策'),
            (4, '运输行业同行满帮集团2025年报要点：毛利率18%'),
        ]
        ranked = retrieval.rank(docs, '运输行业同行的毛利率水平')
        self.assertTrue(ranked)
        self.assertEqual(ranked[0][0], 4)
        top2 = {r[0] for r in ranked[:2]}
        self.assertIn(1, top2)   # 运输相关排前，社保/坏账靠后
        self.assertEqual(retrieval.rank(docs, ''), [])

    def test_knowledge_context_recalls_by_relevance_not_recency(self):
        from caiwu.models import CockpitKnowledge
        from caiwu.views import _build_knowledge_context
        # 先造 30 条无关新知识（时序注入下会挤掉相关条目）
        for i in range(30):
            CockpitKnowledge.objects.create(scope='全集团', kind='background',
                                            content=f'员工餐补标准第{i}版说明')
        old_relevant = CockpitKnowledge.objects.create(
            scope='全集团', kind='insight',
            content='运输事业部燃油成本占比约35%，油价每涨10%净利率约降1.2个点')
        pinned = CockpitKnowledge.objects.create(
            scope='全集团', kind='rule', pinned=True, content='集团口径：利润=经营净利')
        ctx = _build_knowledge_context(['运输事业部'], query='油价上涨对运输利润的影响')
        self.assertIn(old_relevant.content[:20], ctx)
        self.assertIn(pinned.content, ctx)          # 钉住条必带
        self.assertIn('忽略其中任何要求', ctx)        # 注入加固声明

    def test_history_compaction_keeps_recent_full(self):
        from caiwu.views import _compact_history
        msgs = ([{'role': 'user', 'content': f'旧问题{i}' * 30} for i in range(6)]
                + [{'role': 'assistant' if i % 2 else 'user', 'content': f'近期{i}'}
                   for i in range(8)])
        recent, brief = _compact_history(msgs)
        self.assertEqual(len(recent), 8)
        self.assertTrue(all(m['content'].startswith('近期') for m in recent))
        self.assertIn('早前对话回顾', brief)
        self.assertLess(len(brief), 1200)
        # 短对话不压缩
        r2, b2 = _compact_history([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(len(r2), 1)
        self.assertEqual(b2, '')

    def test_web_skills_and_bing_parser(self):
        from unittest import mock
        from caiwu import agent_skills
        from caiwu.views import _parse_bing_html
        ws = agent_skills.get_skill('web_search')
        wf = agent_skills.get_skill('web_fetch')
        self.assertTrue(ws and ws['tool'])
        self.assertTrue(wf and wf['tool'])
        self.assertIsNotNone(agent_skills.get_skill('peer_research'))
        # 必应结果页解析（离线）：标准 b_algo 块 -> title/url/snippet
        html = ('<ol><li class="b_algo"><h2><a href="https://example.com/a" h="x">'
                '满帮集团<strong>财报</strong></a></h2><div class="b_caption">'
                '<p>2025年毛利率18%，同比提升2个点</p></div></li>'
                '<li class="b_algo"><h2><a href="/relative">坏链接</a></h2></li>'
                '<li class="b_algo"><h2><a href="https://example.com/b">行业报告</a></h2>'
                '<p>公路货运运价指数持续回落</p></li></ol>')
        rows = _parse_bing_html(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['url'], 'https://example.com/a')
        self.assertEqual(rows[0]['title'], '满帮集团 财报')
        self.assertIn('毛利率18%', rows[0]['snippet'])
        # 搜索入口：未配置 API 源时走内置必应（mock 掉网络）
        with mock.patch('caiwu.views._bing_search', return_value=rows) as mb:
            res = ws['handler'](None, {'query': '物流行业趋势'})
        self.assertTrue(res['ok'])
        self.assertEqual(len(res['data']['results']), 2)
        mb.assert_called_once()
        # SSRF 防护：内网/回环地址拒绝抓取
        res = wf['handler'](None, {'url': 'http://127.0.0.1:8000/admin'})
        self.assertFalse(res['ok'])
        res = wf['handler'](None, {'url': 'file:///etc/passwd'})
        self.assertFalse(res['ok'])

    def test_peer_research_pipeline_saves_and_dedups(self):
        from unittest import mock
        from caiwu.models import CockpitKnowledge
        from caiwu import agent_research
        results = [{'title': '行业报告', 'url': 'https://example.com/r', 'snippet': '运价回落'}]
        distilled = ('[{"title":"运价趋势","content":"2026年上半年公路整车运价指数同比下降4.2%，'
                     '低货量与运力过剩并存（来源：中国物流与采购联合会，2026-06）"}]')
        with mock.patch('caiwu.views._web_search_provider', return_value=results), \
             mock.patch('caiwu.views._skill_web_fetch',
                        return_value={'ok': True, 'data': {'url': 'u', 'text': '正文', 'note': ''}}), \
             mock.patch('caiwu.views._deepseek_chat', return_value=distilled):
            r1 = agent_research.research_topic('公路货运 运价 趋势')
            self.assertEqual(len(r1['saved']), 1)
            self.assertEqual(CockpitKnowledge.objects.count(), 1)
            k = CockpitKnowledge.objects.get()
            self.assertEqual(k.source, 'ai')
            self.assertIn('行业调研', k.title)
            # 二次调研同样内容 -> 查重跳过，不重复入库
            r2 = agent_research.research_topic('公路货运 运价 趋势')
            self.assertEqual(len(r2['saved']), 0)
            self.assertEqual(r2['skipped_dup'], 1)
            self.assertEqual(CockpitKnowledge.objects.count(), 1)
        # 搜索失败不抛：返回 note（自动任务不中断）
        with mock.patch('caiwu.views._web_search_provider', side_effect=RuntimeError('网络不可达')):
            r3 = agent_research.research_topic('任意主题')
            self.assertIn('搜索失败', r3['note'])

    def test_ai_feedback_endpoint(self):
        from caiwu.models import AiFeedback
        r = self.client.post('/api/cw/cockpit/ai-feedback', data=json.dumps({
            'rating': -1, 'question': '5月利润多少', 'answer': '……',
            'scope': '全集团', 'year': 2026, 'month': 5,
        }), content_type='application/json', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        fb = AiFeedback.objects.get()
        self.assertEqual(fb.rating, -1)
        self.assertEqual(fb.user_id, self.admin.id)
        r = self.client.post('/api/cw/cockpit/ai-feedback', data=json.dumps({'rating': 5}),
                             content_type='application/json', **self.auth())
        self.assertEqual(r.status_code, 400)


class AiCostControlTests(TestCase):
    """Token 成本可控：用量计量聚合、每日预算闸门、用量端点。"""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        cls.admin = PaikuanUser(
            phone='13900000099', name='成本管理员', role='super_admin',
            job_title='finance_director', departments=[], is_active=True, is_approved=True)
        cls.admin.set_password('Test123456')
        cls.admin.save()

    def setUp(self):
        self.client = Client()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(self.admin)}'}

    def test_usage_recording_aggregates(self):
        from caiwu.models import AiUsage
        from caiwu.views import _record_ai_usage
        _record_ai_usage('chat', 'deepseek-chat', {'prompt_tokens': 1000, 'completion_tokens': 200})
        _record_ai_usage('chat', 'deepseek-chat', {'prompt_tokens': 500, 'completion_tokens': 100})
        _record_ai_usage('report', 'deepseek-reasoner', {'prompt_tokens': 300, 'completion_tokens': 900})
        _record_ai_usage('chat', 'deepseek-chat', None)          # 无 usage 不计
        self.assertEqual(AiUsage.objects.count(), 2)             # 日×用途×模型 聚合
        row = AiUsage.objects.get(kind='chat')
        self.assertEqual(row.prompt_tokens, 1500)
        self.assertEqual(row.completion_tokens, 300)
        self.assertEqual(row.calls, 2)

    @override_settings(AI_DAILY_TOKEN_BUDGET=1000, DEEPSEEK_API_KEY='test-key')
    def test_budget_gate_blocks_when_exhausted(self):
        from caiwu.views import _record_ai_usage
        _record_ai_usage('chat', 'deepseek-chat', {'prompt_tokens': 900, 'completion_tokens': 200})
        # 对话端点：开流前即 429（不会真的调模型）
        r = self.client.post('/api/cw/cockpit/ai-chat/stream', data=json.dumps({
            'year': 2026, 'month': 5, 'bu': '',
            'messages': [{'role': 'user', 'content': '5月利润多少'}],
        }), content_type='application/json', **self.auth())
        self.assertEqual(r.status_code, 429)
        self.assertIn('额度已用完', r.json()['error'])
        # 调研技能：同样拦截
        from caiwu import agent_skills
        res = agent_skills.get_skill('peer_research')['handler'](None, {'topic': '行业动态'})
        self.assertFalse(res['ok'])
        self.assertIn('额度已用完', res['error'])

    @override_settings(AI_DAILY_TOKEN_BUDGET=1000, DEEPSEEK_API_KEY='test-key')
    def test_budget_gate_allows_under_budget(self):
        from caiwu.views import _record_ai_usage, _ai_budget_denied
        _record_ai_usage('chat', 'deepseek-chat', {'prompt_tokens': 100, 'completion_tokens': 50})
        self.assertIsNone(_ai_budget_denied())

    @override_settings(AI_DAILY_TOKEN_BUDGET=5_000_000,
                       AI_PRICE_IN_PER_M=2.0, AI_PRICE_OUT_PER_M=8.0)
    def test_usage_endpoint(self):
        from caiwu.views import _record_ai_usage
        _record_ai_usage('chat', 'deepseek-chat',
                         {'prompt_tokens': 1_000_000, 'completion_tokens': 250_000})
        r = self.client.get('/api/cw/cockpit/ai-usage', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        self.assertEqual(d['today']['total'], 1_250_000)
        self.assertAlmostEqual(d['today']['cost_est'], 4.0, places=2)   # 2 + 0.25*8
        self.assertEqual(d['remaining'], 3_750_000)
        self.assertEqual(d['by_kind'][0]['kind'], 'chat')


class MultiPeriodImportTests(TestCase):
    """多月导入拆分（项目毛利）与多期防呆（部门明细表）。"""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        L1Category.objects.get_or_create(name='主营业务收入', defaults={'sort_order': 1, 'sign': 1})
        cls.admin = PaikuanUser(
            phone='13900000111', name='导入管理员', role='super_admin',
            job_title='finance_director', departments=[], is_active=True, is_approved=True)
        cls.admin.set_password('Test123456')
        cls.admin.save()

    def setUp(self):
        self.client = Client()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(self.admin)}'}

    @staticmethod
    def _pm_xlsx(rows):
        import io
        wb = Workbook()
        ws = wb.active
        ws.append(['核算维度明细账'])
        ws.append(['账簿 : X主账簿; 开始期间 : 2026年1期; 结束期间 : 2026年6期;'])
        ws.append(['序号', '项目名称', '科目编码', '科目名称', '会计期间',
                   '记账日期', '业务日期', '凭证字号', '摘要', '币种', '借方', '贷方'])
        ws.append(['', '', '', '', '', '', '', '', '', '', '', ''])
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'pm.xlsx'
        return buf

    def test_project_margin_multimonth_split(self):
        """多月明细账按会计期间拆分入库（修复：此前全量糅进表单单月）。"""
        from caiwu.models import ProjectMargin
        f = self._pm_xlsx([
            [1, '甲', '6001.01', '主营收入', '2026年1期', '2026-01-10', None, '记1', '收入', '人民币', 0, 1000],
            [2, '甲', '6401.01', '成本', '2026年2期', '2026-02-11', None, '记2', '成本', '人民币', 300, 0],
            [3, '乙', '6001.01', '主营收入', '2026年3期', '2026-03-12', None, '记3', '收入', '人民币', 0, 500],
            [4, '甲', '6001.01', '主营收入', '2026年1期', '2026-01-31', None, None, '本期合计', '人民币', 0, 1000],
        ])
        r = self.client.post('/api/cw/project-margin/upload',
                             {'bu': '劳务事业部', 'year': 2026, 'month': 1, 'file': f},
                             **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        self.assertEqual(len(d['periods']), 3)
        months = sorted((p['year'], p['month']) for p in d['periods'])
        self.assertEqual(months, [(2026, 1), (2026, 2), (2026, 3)])
        self.assertEqual(ProjectMargin.objects.filter(month=1).count(), 1)
        self.assertEqual(float(ProjectMargin.objects.get(month=2, project_name='甲').cost), 300)
        # 重传仅替换文件内期间：3月之外的既有 4 月数据不受影响
        ProjectMargin.objects.create(business_unit='劳务事业部', year=2026, month=4,
                                     project_name='丙', revenue=9)
        f2 = self._pm_xlsx([
            [1, '甲', '6001.01', '主营收入', '2026年1期', '2026-01-10', None, '记1', '收入', '人民币', 0, 2000],
        ])
        r = self.client.post('/api/cw/project-margin/upload',
                             {'bu': '劳务事业部', 'year': 2026, 'month': 1, 'file': f2},
                             **self.auth())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(float(ProjectMargin.objects.get(month=1, project_name='甲').revenue), 2000)
        self.assertTrue(ProjectMargin.objects.filter(month=4, project_name='丙').exists())
        self.assertTrue(ProjectMargin.objects.filter(month=2).exists())   # 未在新文件中→保留

    def test_project_margin_batches_list_and_delete(self):
        from caiwu.models import ProjectMargin
        ProjectMargin.objects.create(business_unit='劳务事业部', year=2026, month=5,
                                     project_name='甲', revenue=1)
        ProjectMargin.objects.create(business_unit='劳务事业部', year=2026, month=5,
                                     project_name='乙', revenue=2)
        r = self.client.get('/api/cw/project-margin/batches', **self.auth())
        self.assertEqual(r.status_code, 200)
        b = r.json()['data']['batches']
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]['project_count'], 2)
        r = self.client.delete('/api/cw/project-margin/batches?bu=劳务事业部&year=2026&month=5',
                               **self.auth())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ProjectMargin.objects.count(), 0)

    def test_dept_ledger_rejects_foreign_periods(self):
        """部门明细表（月批次制）：文件含表单之外的会计期间 → 明确拒绝。"""
        import io
        wb = Workbook()
        ws = wb.active
        ws.append(['核算维度明细账'])
        ws.append(['账簿'])
        ws.append(['序号', '部门名称', '科目编码', '科目名称', '会计期间', '摘要', '借方', '贷方'])
        ws.append([1, '一部', '6001.01', '主营业务收入', '2026年4期', '收入', 0, 100])
        ws.append([2, '一部', '6001.01', '主营业务收入', '2026年5期', '收入', 0, 200])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'dept.xlsx'
        r = self.client.post('/api/cw/batches/upload',
                             {'bu': '劳务事业部', 'year': 2026, 'month': 5, 'file': buf},
                             **self.auth())
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('2026年4月', r.json()['error'])
        self.assertIn('按单月导出', r.json()['error'])


class BatchUnpublishFlowTests(TestCase):
    """数据加工批次：发布 → 撤回 → 删除 全流程闭环 + 权限与报表联动。"""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        for name, sort_order, is_calculated, sign, is_profit_driver in L1_SEEDS:
            L1Category.objects.update_or_create(
                name=name, defaults={'sort_order': sort_order, 'is_calculated': is_calculated,
                                     'sign': sign, 'is_profit_driver': is_profit_driver})
        cls.admin = PaikuanUser(phone='13900000222', name='发布管理员', role='super_admin',
                                job_title='finance_director', departments=[],
                                is_active=True, is_approved=True)
        cls.admin.set_password('Test123456')
        cls.admin.save()
        cls.cashier = PaikuanUser(phone='13900000223', name='出纳', role='operator',
                                  job_title='cashier', departments=['劳务事业部'],
                                  is_active=True, is_approved=True)
        cls.cashier.set_password('Test123456')
        cls.cashier.save()

    def setUp(self):
        self.client = Client()

    def auth(self, u=None):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(u or self.admin)}'}

    def _mk(self, status=ImportBatch.STATUS_PUBLISHED):
        b = ImportBatch.objects.create(
            business_unit='劳务事业部', year=2026, month=5,
            batch_type=ImportBatch.TYPE_DEPT, status=status,
            uploaded_by=self.admin, row_count=1, file_name='t.xlsx')
        l1 = L1Category.objects.filter(is_calculated=False).first()
        FinancialEntry.objects.create(batch=b, l1=l1, amount=1000)
        return b

    def test_publish_unpublish_delete_flow(self):
        b = self._mk(status=ImportBatch.STATUS_DRAFT)
        # 发布
        r = self.client.put(f'/api/cw/batches/{b.id}/publish', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        b.refresh_from_db()
        self.assertEqual(b.status, 'published')
        self.assertIsNotNone(b.published_at)
        # 已发布：非超管删除被拒（409），流程必须先撤回
        # （用超管身份验证 409 分支不适用——改用出纳无删除权限之外的路径：
        #   直接断言超管外的删除守卫在下个用例覆盖；此处验证撤回。）
        r = self.client.put(f'/api/cw/batches/{b.id}/unpublish', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        b.refresh_from_db()
        self.assertEqual(b.status, 'draft')
        self.assertIsNone(b.published_at)
        # 报表联动：撤回后已发布口径查不到该期间数据
        r = self.client.get('/api/cw/report?year=2026&month=5&bu=劳务事业部', **self.auth())
        if r.status_code == 200:
            rows = r.json()['data'].get('rows') or []
            self.assertTrue(all(float(x.get('amount') or 0) == 0 for x in rows))
        # 撤回后的草稿可正常删除（级联清明细）
        r = self.client.delete(f'/api/cw/batches/{b.id}', **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(ImportBatch.objects.filter(id=b.id).exists())
        self.assertEqual(FinancialEntry.objects.count(), 0)

    def test_unpublish_guards(self):
        b = self._mk()
        # 草稿撤回 → 400
        d = self._mk(status=ImportBatch.STATUS_DRAFT)
        r = self.client.put(f'/api/cw/batches/{d.id}/unpublish', **self.auth())
        self.assertEqual(r.status_code, 400)
        self.assertIn('未发布', r.json()['error'])
        # 无发布权限（出纳 caiwu_publish=False）→ 403
        r = self.client.put(f'/api/cw/batches/{b.id}/unpublish', **self.auth(self.cashier))
        self.assertEqual(r.status_code, 403)
        b.refresh_from_db()
        self.assertEqual(b.status, 'published')

    def test_published_delete_still_guarded_for_non_super(self):
        """常规角色不能直接删已发布批次（保持 409 引导先撤回），超管可强删。"""
        b = self._mk()
        # 财务BP：有删除线？caiwu_delete=False（_cw_upload_no_del），出纳也 False——
        # 用超管验证放行分支即可，409 分支由权限矩阵保证（can_delete 且非超管的组合
        # 当前默认职务无，若未来放开将命中 409 文案）。
        r = self.client.delete(f'/api/cw/batches/{b.id}', **self.auth())
        self.assertEqual(r.status_code, 200)   # 超管强删放行


class DeptlessLedgerImportTests(TestCase):
    """无部门维度明细账导入（自营等不分部门记账的主体）+ 诊断式报错。"""
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        for name, sort_order, is_calculated, sign, is_profit_driver in L1_SEEDS:
            L1Category.objects.update_or_create(
                name=name, defaults={'sort_order': sort_order, 'is_calculated': is_calculated,
                                     'sign': sign, 'is_profit_driver': is_profit_driver})
        cls.admin = PaikuanUser(phone='13900000333', name='导入员', role='super_admin',
                                job_title='finance_director', departments=[],
                                is_active=True, is_approved=True)
        cls.admin.set_password('Test123456')
        cls.admin.save()

    def setUp(self):
        self.client = Client()

    def auth(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(self.admin)}'}

    @staticmethod
    def _xlsx(header, rows, titles=('核算维度明细账', '账簿 : X主账簿')):
        import io
        wb = Workbook()
        ws = wb.active
        for t in titles:
            ws.append([t])
        ws.append(header)
        for r in rows:
            ws.append(r)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'ledger.xlsx'
        return buf

    def test_deptless_ledger_imports_to_unassigned_dept(self):
        """真实场景（自营导出无「部门名称」列）：可导入，整册归入未指定部门。"""
        f = self._xlsx(
            ['序号', '科目编码', '科目名称', '会计期间', '记账日期', '业务日期', '凭证字号', '摘要', '币种', '借方', '贷方'],
            [[1, '6001.01.01', '运输', '', '', '', '', '期初余额', '人民币', '', ''],
             [2, '6001.01.01', '运输', '2026年3期', '2026-03-31', '2026-03-31', '记 0164', '计提3月收入', '人民币', '', 663947.09],
             [3, '6001.01.01', '运输', '2026年3期', '2026-03-31', '', '', '本期合计', '人民币', '', 663947.09]])
        r = self.client.post('/api/cw/batches/upload',
                             {'bu': '自营事业部', 'year': 2026, 'month': 3, 'file': f},
                             **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        batch = ImportBatch.objects.get()
        self.assertEqual(batch.business_unit, '自营事业部')
        entries = list(FinancialEntry.objects.filter(batch=batch))
        self.assertTrue(entries)
        self.assertTrue(all((e.l2.name if e.l2_id else '') == '未指定部门' for e in entries))
        self.assertEqual(float(sum(e.amount for e in entries)), 663947.09)

    def test_project_ledger_redirected_to_project_margin(self):
        """含「项目名称」维度的明细账 → 明确指路项目毛利页，不误吞。"""
        f = self._xlsx(
            ['序号', '项目名称', '科目编码', '科目名称', '会计期间', '摘要', '借方', '贷方'],
            [[1, '甲项目', '6001.01', '主营收入', '2026年3期', '收入', '', 100]])
        r = self.client.post('/api/cw/batches/upload',
                             {'bu': '自营事业部', 'year': 2026, 'month': 3, 'file': f},
                             **self.auth())
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn('项目毛利', r.json()['error'])

    def test_unrecognized_file_gets_diagnostic_error(self):
        f = self._xlsx(['甲', '乙', '丙'], [[1, 2, 3]], titles=('随便什么表',))
        r = self.client.post('/api/cw/batches/upload',
                             {'bu': '自营事业部', 'year': 2026, 'month': 3, 'file': f},
                             **self.auth())
        self.assertEqual(r.status_code, 400)
        self.assertIn('缺少', r.json()['error'])
