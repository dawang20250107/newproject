"""月末关账清单（close checklist）：把散落各页的关账前置检查聚合成一页红绿灯。

每项检查返回 {key, label, status, value, detail, link}：
  status ∈ ok(绿·已就绪) / warn(黄·有风险需处理) / todo(红·未完成)
  link 为系统内直达路由（前端 router.push），value 为一句话结论。

只读聚合，不改任何数据；各项口径直接复用对应模块的权威实现，杜绝第二套算法。
"""
import calendar
import datetime
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from caiwu.models import BUSINESS_UNITS, ImportBatch, InternalBatch, ProjectMargin
from caiwu.views import cw_required, ok, err, _page_denied, _can_access_bu
from caiwu.views_internal import _positions


def _month_range(year, month):
    return (datetime.date(year, month, 1),
            datetime.date(year, month, calendar.monthrange(year, month)[1]))


def _fmt_wan(v):
    try:
        return f'{float(v) / 10000:,.2f}万'
    except (TypeError, ValueError):
        return '0万'


@csrf_exempt
@cw_required()
def close_checklist(request):
    """GET ?year=&month= → 月末关账清单（红绿灯 + 直达链接）。"""
    denied = _page_denied(request, 'report')
    if denied:
        return denied
    try:
        year = int(request.GET.get('year', ''))
        month = int(request.GET.get('month', ''))
    except (TypeError, ValueError):
        return err('年份或月份无效')
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return err('年份或月份无效')

    start, end = _month_range(year, month)
    today = timezone.localdate()

    # 可见范围：caiwu 域按 BUSINESS_UNITS×_can_access_bu；ar/排款域按 DEPARTMENTS×pk_depts
    bus = [b for b in BUSINESS_UNITS if _can_access_bu(request, b)]
    from paikuan.views import DEPARTMENTS, VALID_DEPARTMENTS
    if request.pk_role == 'super_admin':
        depts = list(DEPARTMENTS)
    else:
        depts = [d for d in (request.pk_depts or []) if d in VALID_DEPARTMENTS]

    items = []

    def add(key, label, status, value, link, detail=''):
        items.append({'key': key, 'label': label, 'status': status,
                      'value': value, 'detail': detail, 'link': link})

    # ── 1. 部门明细表提交发布 ─────────────────────────────────────────────────
    # 注：TYPE_PL(手工利润表)为遗留常量——上传路径只建部门明细表，利润表校验由
    # _compute_pl_check 从明细表推算，系统中不存在「上传利润表」操作，故不设此检查项
    pub = set(ImportBatch.objects.filter(
        year=year, month=month, batch_type=ImportBatch.TYPE_DEPT,
        status=ImportBatch.STATUS_PUBLISHED, business_unit__in=bus)
        .values_list('business_unit', flat=True))
    missing = [b for b in bus if b not in pub]
    add('dept_report', '部门明细表发布',
        'ok' if not missing else 'todo',
        f'{len(pub)}/{len(bus)} 个事业部已发布',
        '/caiwu/data',
        '未发布：' + '、'.join(missing) if missing else '全部就绪')

    # ── 3. 项目毛利导入 ───────────────────────────────────────────────────────
    pm_bus = set(ProjectMargin.objects.filter(year=year, month=month, business_unit__in=bus)
                 .values_list('business_unit', flat=True).distinct())
    pm_missing = [b for b in bus if b not in pm_bus]
    add('project_margin', '项目毛利核算账导入',
        'ok' if not pm_missing else 'todo',
        f'{len(pm_bus)}/{len(bus)} 个事业部已导入',
        '/caiwu/project-margin',
        '未导入：' + '、'.join(pm_missing) if pm_missing else '全部就绪')

    # ── 4. 内部往来对账（集团口径，与差异矩阵同源 _positions）────────────────────
    uploaded = set(InternalBatch.objects.filter(year=year, month=month)
                   .values_list('business_unit', flat=True))
    pos, _mode = _positions(year, month)
    total_diff, pairs, pairs_ok = Decimal('0'), 0, 0
    seen = set()
    for (a, cp), pa in pos.items():
        if (cp, a) in seen or a == cp:
            continue
        seen.add((a, cp))
        pb = pos.get((cp, a), Decimal('0'))
        if not pa and not pb:
            continue
        if a in uploaded and cp in uploaded:
            pairs += 1
            d = pa + pb
            if abs(d) < Decimal('0.005'):
                pairs_ok += 1
            else:
                total_diff += abs(d)
    if not uploaded:
        add('internal', '内部往来对账', 'todo', '本月尚未上传任何主体的内往数据',
            '/caiwu/data', '')
    elif total_diff > 0:
        add('internal', '内部往来对账', 'warn',
            f'{pairs_ok}/{pairs} 对已平，未平差异合计 {_fmt_wan(total_diff)}',
            '/caiwu/data', f'已上传 {len(uploaded)} 个主体')
    else:
        add('internal', '内部往来对账', 'ok',
            f'{pairs} 对全部轧平（已上传 {len(uploaded)} 个主体）', '/caiwu/data', '')

    # ── 5. 预算达成（现金口径，与预算页/周期报表同源）────────────────────────────
    from ar.models import CollectionBudget, ARPayment, ARRecord, AdvanceRecord
    from ar.models import NON_CASH_PAYMENT_SOURCES
    from paikuan.models import Payment, PaymentInstallment, ApprovalRecord
    bc = CollectionBudget.objects.filter(
        expected_date__range=(start, end), delivery_dept__in=depts
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    ac = ARPayment.objects.filter(
        payment_date__range=(start, end), ar_record__delivery_dept__in=depts
    ).exclude(source__in=NON_CASH_PAYMENT_SOURCES).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    if bc <= 0:
        add('budget', '回款预算达成', 'warn', '本月未录入回款预算', '/ar/budget', '')
    else:
        rate = float(ac / bc * 100)
        add('budget', '回款预算达成',
            'ok' if rate >= 100 else 'warn',
            f'达成 {rate:.1f}%（实际 {_fmt_wan(ac)} / 预算 {_fmt_wan(bc)}）',
            '/ar/budget', '')

    # ── 6. 本月净现金流（统一口径 cash_flow_window）──────────────────────────────
    from ar.views._common import cash_flow_window
    cw = cash_flow_window(depts, start, end)
    add('cashflow', '本月净现金流',
        'ok' if cw['net'] >= 0 else 'warn',
        f'净额 {_fmt_wan(cw["net"])}（流入 {_fmt_wan(cw["inflow"])} − 流出 {_fmt_wan(cw["outflow"])}）',
        '/caiwu/cockpit', '口径：现金收付制，与现金流分析一致')

    # ── 7. 资金池期初配置 ─────────────────────────────────────────────────────
    from ar.models import CashPoolConfig
    cfg_depts = set(CashPoolConfig.objects.filter(delivery_dept__in=depts)
                    .values_list('delivery_dept', flat=True))
    cfg_missing = [d for d in depts if d not in cfg_depts]
    add('pool', '资金池期初配置',
        'ok' if not cfg_missing else 'warn',
        f'{len(cfg_depts)}/{len(depts)} 个事业部已配置期初',
        '/caiwu/cockpit',
        '未配置：' + '、'.join(cfg_missing) if cfg_missing else '全部就绪')

    # ── 8. 逾期应收 ──────────────────────────────────────────────────────────
    od = (ARRecord.objects.filter(delivery_dept__in=depts, outstanding_amount__gt=0,
                                  due_date__lt=today)
          .aggregate(s=Sum('outstanding_amount'), c=Count('id')))
    od_amt, od_cnt = od['s'] or Decimal('0'), od['c'] or 0
    add('ar_overdue', '逾期应收在外',
        'ok' if od_amt <= 0 else 'warn',
        f'{od_cnt} 笔合计 {_fmt_wan(od_amt)}' if od_cnt else '无逾期应收',
        '/ar/records?status=overdue', '')

    # ── 9. 逾期未付排款（与资金池「刚性待付·已到期」同口径）──────────────────────
    from paikuan.views import _paid_subq
    pay_od = (Payment.objects.filter(department__in=depts, deleted_at__isnull=True)
              .annotate(paid_sum=_paid_subq())
              .annotate(plan=Coalesce('plan_adjustment', 'total_amount'))
              .annotate(rem=F('plan') - F('paid_sum') - F('prepaid_offset_amount'))
              .filter(rem__gt=0, planned_date__lte=today)
              .aggregate(s=Sum('rem'), c=Count('id')))
    p_amt, p_cnt = pay_od['s'] or Decimal('0'), pay_od['c'] or 0
    add('pay_overdue', '逾期未付排款',
        'ok' if p_amt <= 0 else 'warn',
        f'{p_cnt} 笔剩余应付 {_fmt_wan(p_amt)}' if p_cnt else '无逾期未付',
        '/payments?status=overdue', '')

    # ── 10. 审批在途 ─────────────────────────────────────────────────────────
    appr = ApprovalRecord.objects.filter(department__in=depts, deleted_at__isnull=True)
    pend = appr.filter(status='pending').aggregate(s=Sum('amount'), c=Count('id'))
    to_sched = appr.filter(status='approved', archived=False).aggregate(
        s=Sum(F('amount') - F('scheduled_amount')), c=Count('id'))
    parts = []
    if pend['c']:
        parts.append(f'待审批 {pend["c"]} 笔 {_fmt_wan(pend["s"])}')
    if to_sched['c']:
        parts.append(f'已批待排 {to_sched["c"]} 笔 {_fmt_wan(to_sched["s"])}')
    add('approvals', '审批在途处理',
        'ok' if not parts else 'warn',
        '；'.join(parts) if parts else '无在途审批',
        '/approvals', '')

    # ── 11. 预收预付逾期挂账 ──────────────────────────────────────────────────
    adv_od = (AdvanceRecord.objects.filter(delivery_dept__in=depts, balance_amount__gt=0,
                                           expected_writeoff_date__lt=today)
              .aggregate(s=Sum('balance_amount'), c=Count('id')))
    a_amt, a_cnt = adv_od['s'] or Decimal('0'), adv_od['c'] or 0
    add('advances', '预收预付逾期挂账',
        'ok' if a_amt <= 0 else 'warn',
        f'{a_cnt} 笔余额 {_fmt_wan(a_amt)} 超预计核销日' if a_cnt else '无逾期挂账',
        '/ar/advances', '')

    # ── 12. 回收站待处理 ─────────────────────────────────────────────────────
    trash_cnt = (ApprovalRecord.objects.filter(deleted_at__isnull=False,
                                               department__in=depts).count()
                 + Payment.objects.filter(deleted_at__isnull=False,
                                          department__in=depts).count())
    add('trash', '回收站待处理',
        'ok' if trash_cnt == 0 else 'warn',
        f'{trash_cnt} 条软删记录待还原或彻底删除' if trash_cnt else '回收站已清空',
        '/trash', '关账前确认回收站里没有该还原的记录')

    n_ok = sum(1 for i in items if i['status'] == 'ok')
    n_todo = sum(1 for i in items if i['status'] == 'todo')
    n_warn = len(items) - n_ok - n_todo
    return ok({'year': year, 'month': month, 'items': items,
               'summary': {'ok': n_ok, 'warn': n_warn, 'todo': n_todo, 'total': len(items)}})
