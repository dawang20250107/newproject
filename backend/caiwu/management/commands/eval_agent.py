"""AI 助手评测：黄金问题集 + 数字对账器。

用法（需 DEEPSEEK_API_KEY，对真实库跑，只读）：
    python manage.py eval_agent --year 2026 --month 5 [--uid 1]

两类检查：
1. 黄金问题集：一组有确定口径答案的经营问题，断言 AI 回答包含由数据库
   实时计算出的关键数字（改提示词/换模型后跑一遍即知有无回归）。
2. 数字对账器：抽取 AI 回答中的「N万/N亿」金额，回验其是否出现在
   数据上下文或工具结果里——抓"编数字"式幻觉。

结果逐题打印 PASS/FAIL 与差异说明；任一 FAIL 时退出码 1。
"""
import json
import re

from django.conf import settings
from django.core.management.base import BaseCommand


def _fmt_wan_variants(v):
    """一个金额的可接受表述集合（万元一位/两位小数、整数）。"""
    w = float(v) / 1e4
    return {f'{w:.0f}', f'{w:.1f}', f'{w:.2f}'}


def _extract_wan_numbers(text):
    """抽取回答中的 N万 / N亿 金额（含千分位），统一折算成「万」返回浮点集合。"""
    out = set()
    for m in re.finditer(r'([-+]?[\d,]+(?:\.\d+)?)\s*(万|亿)', text):
        try:
            n = float(m.group(1).replace(',', ''))
        except ValueError:
            continue
        out.add(round(n * (10000 if m.group(2) == '亿' else 1), 2))
    return out


class Command(BaseCommand):
    help = 'AI 助手评测：黄金问题集 + 数字对账（只读，需 DEEPSEEK_API_KEY）'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--month', type=int, required=True)
        parser.add_argument('--uid', type=int, default=None,
                            help='以哪个平台账号身份执行（默认取第一个 super_admin）')

    def handle(self, *args, **opts):
        if not settings.DEEPSEEK_API_KEY:
            self.stderr.write('未配置 DEEPSEEK_API_KEY，无法评测')
            raise SystemExit(2)
        from django.test import RequestFactory
        from paikuan.models import PaikuanUser
        from caiwu import views as cw

        year, month = opts['year'], opts['month']
        if opts['uid']:
            user = PaikuanUser.objects.get(id=opts['uid'])
        else:
            user = PaikuanUser.objects.filter(role='super_admin', is_active=True).first()
        if not user:
            self.stderr.write('找不到可用账号')
            raise SystemExit(2)

        # 用驾驶舱同源口径算出"标准答案"数字
        bus = [b for b in cw.BUSINESS_UNITS]
        bu_rows, ov_m, ov_y, actuals = cw._compute_cockpit_rows(bus, year, month)
        data_pack = cw._build_cockpit_data_pack(year, month, bus, bu_rows, ov_m, ov_y, actuals)
        pack_numbers = _extract_wan_numbers(data_pack)

        golden = []
        rev = (ov_m or {}).get('revenue')
        pf = (ov_m or {}).get('profit')
        if rev:
            golden.append((f'{year}年{month}月全集团收入是多少？', _fmt_wan_variants(rev)))
        if pf:
            golden.append((f'{year}年{month}月全集团经营净利是多少？', _fmt_wan_variants(pf)))
        golden.append((f'{year}年{month}月哪个事业部利润最好？给出金额。', None))
        if not golden:
            self.stderr.write('该期间无已发布数据，无法构造黄金问题')
            raise SystemExit(2)

        rf = RequestFactory()
        failures = 0
        for q, expect in golden:
            req = rf.post('/api/cw/cockpit/ai-chat/stream', data=json.dumps({
                'year': year, 'month': month, 'bu': '',
                'messages': [{'role': 'user', 'content': q}],
            }), content_type='application/json')
            req.pk_user, req.pk_uid = user, user.id
            req.pk_role, req.pk_job = user.role, user.job_title
            req.pk_depts = user.departments or []
            resp = cw.cockpit_ai_chat_stream(req)
            answer = ''
            for chunk in resp.streaming_content:
                for line in chunk.decode('utf-8', errors='replace').split('\n'):
                    if not line.startswith('data:'):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if ev.get('type') == 'answer':
                        answer += ev.get('delta') or ''
            ok = True
            notes = []
            if expect is not None and not any(v in answer for v in expect):
                ok = False
                notes.append(f'期望包含金额（万）之一 {sorted(expect)}，未命中')
            # 数字对账：回答中的万级金额应能在数据包中找到（±0.5% 容差）
            bogus = []
            for n in _extract_wan_numbers(answer):
                if abs(n) < 1:
                    continue
                if not any(abs(n - p) <= max(0.5, abs(p) * 0.005) for p in pack_numbers):
                    bogus.append(n)
            if len(bogus) > 3:   # 少量派生数（如自算差额/比率折金额）豁免，成串对不上即挂
                ok = False
                notes.append(f'疑似无出处金额（万）：{sorted(bogus)[:6]}')
            failures += (not ok)
            self.stdout.write(f"[{'PASS' if ok else 'FAIL'}] {q}")
            for nline in notes:
                self.stdout.write(f'       {nline}')
            self.stdout.write(f'       答：{answer[:160]}...')
        self.stdout.write(f'\n共 {len(golden)} 题，失败 {failures} 题')
        if failures:
            raise SystemExit(1)
