"""临时 E2E：用真实金蝶导出回放内部往来全链路（本地验证用，不入库）。"""
import os
import unittest

from django.test import Client, TestCase

from caiwu.models import InternalBalance, InternalBatch
from caiwu.views import _make_token
from paikuan.models import PaikuanUser

UP = '/root/.claude/uploads/6fd330e7-bc1e-50fe-8028-0f11aa8b8ac7/'
DETAIL = UP + '5d6ec9bb-_____________________3___2026_5__2026_5_.xlsx'
BALANCE = UP + 'c67be1b1-________________3___2026_5__2026_5_.xlsx'


@unittest.skipUnless(os.path.exists(DETAIL), '真实样本不存在，跳过')
class InternalE2ERealFiles(TestCase):
    databases = {'default'}

    @classmethod
    def setUpTestData(cls):
        cls.admin = PaikuanUser(phone='13911112222', name='E2E管理员', role='super_admin',
                                job_title='finance_director', departments=[],
                                is_active=True, is_approved=True)
        cls.admin.set_password('T3st123456')
        cls.admin.save()
        cls.cashier = PaikuanUser(phone='13911113333', name='出纳', role='operator',
                                  job_title='cashier', departments=['劳务事业部'],
                                  is_active=True, is_approved=True)
        cls.cashier.set_password('T3st123456')
        cls.cashier.save()

    def setUp(self):
        self.client = Client()

    def auth(self, u=None):
        return {'HTTP_AUTHORIZATION': f'Bearer {_make_token(u or self.admin)}'}

    def test_full_chain(self):
        # 1 出纳无 internal 页权限 → 403
        r = self.client.get('/api/cw/internal/matrix?year=2026&month=5', **self.auth(self.cashier))
        print('\n1 出纳访问矩阵 =>', r.status_code)
        self.assertEqual(r.status_code, 403)

        # 2 真实明细分类账
        with open(DETAIL, 'rb') as f:
            r = self.client.post('/api/cw/internal/upload', {'file': f, 'year': 2026, 'month': 5},
                                 **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        print('2 明细上传 kind:', d['kind'], 'rows:', d['rows'],
              '批次:', [(b['business_unit'], b['row_count']) for b in d['batches']])
        self.assertEqual(d['kind'], 'detail')
        self.assertEqual(d['rows'], 748)

        # 3 真实余额表
        with open(BALANCE, 'rb') as f:
            r = self.client.post('/api/cw/internal/upload', {'file': f, 'year': 2026, 'month': 5},
                                 **self.auth())
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()['data']
        print('3 余额上传 kind:', d['kind'], 'rows:', d['rows'],
              '主体:', [b['business_unit'] for b in d['batches']])
        self.assertEqual(d['kind'], 'balance')
        self.assertEqual(d['rows'], 18)

        # 4 覆盖
        r = self.client.get('/api/cw/internal/batches?year=2026&month=5', **self.auth())
        d = r.json()['data']
        cov = {u: {k: v['row_count'] for k, v in (b or {}).items()}
               for u, b in zip(d['units'], d['batches']) if b}
        print('4 覆盖:', cov)
        self.assertIn('集团总部', cov)
        self.assertIn('detail', cov['集团总部'])
        self.assertIn('balance', cov['集团总部'])

        # 5 矩阵：期末余额口径；劳务⇄阔展核平
        r = self.client.get('/api/cw/internal/matrix?year=2026&month=5', **self.auth())
        d = r.json()['data']
        print('5 矩阵 mode:', d['mode'], 'kpi:', {k: round(v, 2) for k, v in d['kpi'].items()})
        self.assertEqual(d['mode'], 'balance')
        lk = next(p for p in d['pairs'] if {p['a'], p['b']} == {'劳务事业部', '阔展事业部'})
        self.assertAlmostEqual(lk['diff'], 0.0, places=2)
        lz = next(p for p in d['pairs'] if {p['a'], p['b']} == {'劳务事业部', '集团总部'})
        self.assertAlmostEqual(abs(lz['diff']), 56141.07, places=2)
        print('   劳务⇄阔展 diff:', round(lk['diff'], 2), '劳务⇄总部 diff:', round(lz['diff'], 2))

        # 6 两两：劳务⇄总部（明细+余额摘要）
        r = self.client.get('/api/cw/internal/pair?year=2026&month=5&a=劳务事业部&b=集团总部',
                            **self.auth())
        d = r.json()['data']
        print('6 两两 a行:', len(d['a_rows']), 'b行:', len(d['b_rows']),
              '配对:', d['matched_pairs'], '对', round(d['matched_amount'], 2),
              '明细差异:', round(d['diff'], 2),
              '余额期初差:', round(d['balance']['opening_diff'], 2),
              '期末差:', round(d['balance']['closing_diff'], 2))
        self.assertIsNotNone(d['balance'])
        self.assertGreater(d['matched_pairs'], 0)
        # 会计恒等式：期末差 = 期初差 + 本期明细差（同口径同期间时）
        self.assertAlmostEqual(d['balance']['closing_diff'],
                               d['balance']['opening_diff'] + d['diff'], places=2)

        # 7 出纳上传拒绝
        with open(BALANCE, 'rb') as f:
            r = self.client.post('/api/cw/internal/upload', {'file': f, 'year': 2026, 'month': 5},
                                 **self.auth(self.cashier))
        print('7 出纳上传 =>', r.status_code)
        self.assertEqual(r.status_code, 403)

        # 8 重传幂等
        with open(BALANCE, 'rb') as f:
            r = self.client.post('/api/cw/internal/upload', {'file': f, 'year': 2026, 'month': 5},
                                 **self.auth())
        self.assertEqual(r.status_code, 200)
        print('8 重传后余额行:', InternalBalance.objects.count())
        self.assertEqual(InternalBalance.objects.count(), 18)

        # 9 删除级联
        bid = InternalBatch.objects.filter(kind='balance').first().id
        r = self.client.delete(f'/api/cw/internal/batches/{bid}', **self.auth())
        self.assertEqual(r.status_code, 200)
        print('9 删除批次后剩余余额行:', InternalBalance.objects.count())
