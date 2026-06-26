"""排款系统账龄 / 逾期 / 预算预警日报（供外部调度器调用，可管道至邮件/IM）。

    # 每个工作日 08:30 生成逾期与预算预警日报
    30 8 * * 1-5 cd /app/backend && python manage.py pk_aging_digest

输出（纯文本，便于 cron 邮件）：
  1. 逾期未付：计划付款日已过、仍未付清的排款，按事业部聚合（条数 + 剩余金额）
  2. 本月预算预警：各事业部本月已排款 vs 付款预算（AR PaymentBudget），超支项标红

只读，不写库；--json 输出机器可读结构（便于后续接入通知中心）。
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import F, Sum, Count
from django.utils import timezone

from paikuan.models import Payment, PaymentPlanItem
from paikuan.views import _paid_expr, _remaining_expr


class Command(BaseCommand):
    help = '逾期未付 + 本月预算预警日报'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='输出 JSON')
        parser.add_argument('--overdue-days', type=int, default=0,
                            help='逾期判定宽限天数（默认 0 = 计划日当天后即逾期）')

    def handle(self, *args, **opts):
        today = timezone.localdate()
        grace = timedelta(days=opts['overdue_days'])
        cutoff = today - grace

        # 1. 逾期未付：planned_date < cutoff 且未付清，按事业部聚合
        overdue = (Payment.objects.filter(deleted_at__isnull=True)
                   .annotate(paid=_paid_expr())
                   .filter(paid__lt=F('total_amount'), planned_date__lt=cutoff)
                   .values('department')
                   .annotate(n=Count('id'), remaining=Sum(_remaining_expr()))
                   .order_by('-remaining'))
        overdue_rows = [
            {'department': o['department'], 'count': o['n'],
             'remaining': str(o['remaining'] or Decimal('0'))}
            for o in overdue
        ]

        # 2. 本月预算预警：各事业部本月已排款 vs 付款预算
        ym = (today.year, today.month)
        sched = (PaymentPlanItem.objects
                 .filter(payment__deleted_at__isnull=True,
                         planned_date__year=ym[0], planned_date__month=ym[1])
                 .values('payment__department')
                 .annotate(s=Sum('amount')))
        sched_by_dept = {r['payment__department']: (r['s'] or Decimal('0')) for r in sched}

        budget_by_dept = {}
        try:
            from ar.models import PaymentBudget
            for r in (PaymentBudget.objects
                      .filter(expected_date__year=ym[0], expected_date__month=ym[1])
                      .values('delivery_dept').annotate(s=Sum('amount'))):
                budget_by_dept[r['delivery_dept']] = r['s'] or Decimal('0')
        except Exception:
            pass

        budget_rows = []
        for dept in sorted(set(sched_by_dept) | set(budget_by_dept)):
            b = budget_by_dept.get(dept)
            s = sched_by_dept.get(dept, Decimal('0'))
            row = {'department': dept, 'scheduled': str(s),
                   'budget': str(b) if b is not None else None,
                   'over': bool(b is not None and s > b),
                   'over_by': str(s - b) if (b is not None and s > b) else '0'}
            budget_rows.append(row)

        if opts['json']:
            self.stdout.write(json.dumps({
                'date': str(today),
                'overdue': overdue_rows,
                'budget': budget_rows,
            }, ensure_ascii=False))
            return

        self.stdout.write(f'═══ 排款日报 {today} ═══')
        self.stdout.write('\n【逾期未付】')
        if not overdue_rows:
            self.stdout.write('  ✓ 无逾期记录')
        for o in overdue_rows:
            self.stdout.write(f"  · {o['department']}: {o['count']} 条，剩余 ¥{o['remaining']}")
        self.stdout.write('\n【本月预算预警】')
        if not budget_rows:
            self.stdout.write('  （本月暂无排款/预算数据）')
        for r in budget_rows:
            if r['budget'] is None:
                self.stdout.write(f"  · {r['department']}: 已排 ¥{r['scheduled']}（未设预算）")
            elif r['over']:
                self.stdout.write(self.style.ERROR(
                    f"  ⚠ {r['department']}: 已排 ¥{r['scheduled']} / 预算 ¥{r['budget']} → 超支 ¥{r['over_by']}"))
            else:
                self.stdout.write(f"  · {r['department']}: 已排 ¥{r['scheduled']} / 预算 ¥{r['budget']}")
