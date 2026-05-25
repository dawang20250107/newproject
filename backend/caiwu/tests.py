import json
from decimal import Decimal

from django.test import Client, TestCase, override_settings
from openpyxl import Workbook

from caiwu.models import (
    BUSINESS_UNITS,
    CaiwuUser,
    FinancialEntry,
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
    databases = {'default', 'caiwu'}

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
        cls.admin = CaiwuUser(
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
