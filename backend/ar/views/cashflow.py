"""资金对比（cashflow comparison）业务域：应收回款 vs 应付付款 的时间轴对比。共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

# ══════════════════════════════════════════════════════════════════════════════
# Cashflow comparison (AR collected vs AP paid)
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@pk_required()
def cashflow(request):
    denied = _page_denied(request, 'ar_cashflow')
    if denied:
        return denied

    # Date range — accept day-level start_date/end_date; fall back to year/month
    today = datetime.date.today()
    start_date_raw = (request.GET.get('start_date') or '').strip()
    end_date_raw = (request.GET.get('end_date') or '').strip()
    if start_date_raw and end_date_raw:
        try:
            start_date = datetime.date.fromisoformat(start_date_raw)
            end_date = datetime.date.fromisoformat(end_date_raw)
        except ValueError:
            return err('日期格式错误，应为 YYYY-MM-DD')
        if end_date < start_date:
            return err('结束日期不能早于起始日期')
        start_year, start_month = start_date.year, start_date.month
        end_year, end_month = end_date.year, end_date.month
    else:
        start_year = _int_param(request, 'start_year', today.year)
        start_month = _int_param(request, 'start_month', 1)
        end_year = _int_param(request, 'end_year', today.year)
        end_month = _int_param(request, 'end_month', today.month)
        start_date = datetime.date(start_year, start_month, 1)
        end_date = datetime.date(end_year, end_month,
                                 calendar.monthrange(end_year, end_month)[1])

    # Departments to show
    if request.pk_role == 'super_admin':
        allowed = DEPARTMENTS
    else:
        allowed = request.pk_depts
    depts_param = request.GET.get('depts', '').strip()
    if depts_param:
        requested = [d.strip() for d in depts_param.split(',') if d.strip()]
        depts = [d for d in requested if d in allowed]
    else:
        depts = list(allowed)

    # Build month list
    months = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    month_keys = [f'{y}-{m:02d}' for y, m in months]

    # AR collections by month across all requested depts.
    # 排除非现金来源（预收抵扣/内部往来）：其不构成现金流入，计入会虚增现金。
    ar_coll = (ARPayment.objects
               .filter(payment_date__gte=start_date, payment_date__lte=end_date,
                       ar_record__delivery_dept__in=depts)
               .exclude(source__in=NON_CASH_PAYMENT_SOURCES)
               .annotate(ym=TruncMonth('payment_date'))
               .values('ym', 'ar_record__delivery_dept')
               .annotate(collected=Sum('amount')))
    coll_map = defaultdict(lambda: defaultdict(Decimal))
    for row in ar_coll:
        ym = row['ym'].strftime('%Y-%m')
        dept = row['ar_record__delivery_dept']
        coll_map[dept][ym] += row['collected'] or Decimal('0')

    # AP payments from installments subtable, grouped by month + department
    paid_map = defaultdict(lambda: defaultdict(Decimal))
    inst_qs = (PaymentInstallment.objects
               .filter(pay_date__gte=start_date, pay_date__lte=end_date,
                       payment__department__in=depts)
               .annotate(ym=TruncMonth('pay_date'))
               .values('ym', 'payment__department')
               .annotate(paid=Sum('pay_amount')))
    for row in inst_qs:
        ym = row['ym'].strftime('%Y-%m')
        dept = row['payment__department']
        paid_map[dept][ym] += row['paid'] or Decimal('0')

    # 扣除预付核销冲抵：按最早实付日期（首个 installment 付款日期，否则 planned_date）归月
    from django.db.models import OuterRef, Subquery
    earliest_inst_date = Subquery(
        PaymentInstallment.objects.filter(payment_id=OuterRef('pk'))
            .order_by('pay_date').values('pay_date')[:1]
    )
    po_qs = (Payment.objects
             .filter(department__in=depts, prepaid_offset_amount__gt=0)
             .annotate(first_pay_date=earliest_inst_date)
             .annotate(attr_ym=TruncMonth(Coalesce('first_pay_date', 'planned_date')))
             .filter(attr_ym__gte=start_date, attr_ym__lte=end_date)
             .values('attr_ym', 'department')
             .annotate(offset=Sum('prepaid_offset_amount')))
    for row in po_qs:
        ym = row['attr_ym'].strftime('%Y-%m')
        dept = row['department']
        paid_map[dept][ym] = max(Decimal('0'),
                                 paid_map[dept].get(ym, Decimal('0')) - (row['offset'] or Decimal('0')))

    # 预收(流入) / 预付(流出) by occur_date month — advances move cash on occur_date
    adv_recv_map = defaultdict(lambda: defaultdict(Decimal))
    adv_paid_map = defaultdict(lambda: defaultdict(Decimal))
    adv_qs = (AdvanceRecord.objects
              .filter(occur_date__gte=start_date, occur_date__lte=end_date,
                      delivery_dept__in=depts)
              .annotate(ym=TruncMonth('occur_date'))
              .values('ym', 'delivery_dept', 'direction')
              .annotate(amt=Sum('advance_amount')))
    for row in adv_qs:
        ym = row['ym'].strftime('%Y-%m')
        target = adv_recv_map if row['direction'] == '预收' else adv_paid_map
        target[row['delivery_dept']][ym] += row['amt'] or Decimal('0')

    # Also include budget data for comparison
    budget_coll_map = defaultdict(lambda: defaultdict(Decimal))
    bc_qs = (CollectionBudget.objects
             .filter(expected_date__gte=start_date, expected_date__lte=end_date,
                     delivery_dept__in=depts)
             .annotate(ym=TruncMonth('expected_date'))
             .values('ym', 'delivery_dept')
             .annotate(budget=Sum('amount')))
    for row in bc_qs:
        ym = row['ym'].strftime('%Y-%m')
        budget_coll_map[row['delivery_dept']][ym] += row['budget'] or Decimal('0')

    budget_paid_map = defaultdict(lambda: defaultdict(Decimal))
    bp_qs = (PaymentBudget.objects
             .filter(expected_date__gte=start_date, expected_date__lte=end_date,
                     delivery_dept__in=depts)
             .annotate(ym=TruncMonth('expected_date'))
             .values('ym', 'delivery_dept')
             .annotate(budget=Sum('amount')))
    for row in bp_qs:
        ym = row['ym'].strftime('%Y-%m')
        budget_paid_map[row['delivery_dept']][ym] += row['budget'] or Decimal('0')

    # Build per-dept series + total
    by_dept = []
    total_coll = defaultdict(Decimal)
    total_paid = defaultdict(Decimal)
    total_adv_recv = defaultdict(Decimal)
    total_adv_paid = defaultdict(Decimal)
    total_bcoll = defaultdict(Decimal)
    total_bpaid = defaultdict(Decimal)
    has_alert = False

    for dept in depts:
        series_coll = [float(coll_map[dept].get(ym, 0)) for ym in month_keys]
        series_paid = [float(paid_map[dept].get(ym, 0)) for ym in month_keys]
        series_arecv = [float(adv_recv_map[dept].get(ym, 0)) for ym in month_keys]
        series_apaid = [float(adv_paid_map[dept].get(ym, 0)) for ym in month_keys]
        series_bcoll = [float(budget_coll_map[dept].get(ym, 0)) for ym in month_keys]
        series_bpaid = [float(budget_paid_map[dept].get(ym, 0)) for ym in month_keys]
        # 流入 = 回款 + 预收；流出 = 付款 + 预付
        inflow = [series_coll[i] + series_arecv[i] for i in range(len(month_keys))]
        outflow = [series_paid[i] + series_apaid[i] for i in range(len(month_keys))]
        alert_months = [month_keys[i] for i in range(len(month_keys))
                        if outflow[i] > inflow[i] > 0]
        if alert_months:
            has_alert = True
        by_dept.append({
            'dept': dept,
            'collected': series_coll,
            'paid': series_paid,
            'advance_received': series_arecv,
            'advance_paid': series_apaid,
            'budget_collection': series_bcoll,
            'budget_payment': series_bpaid,
            'alert_months': alert_months,
        })
        for i, ym in enumerate(month_keys):
            total_coll[ym] += coll_map[dept].get(ym, Decimal('0'))
            total_paid[ym] += paid_map[dept].get(ym, Decimal('0'))
            total_adv_recv[ym] += adv_recv_map[dept].get(ym, Decimal('0'))
            total_adv_paid[ym] += adv_paid_map[dept].get(ym, Decimal('0'))
            total_bcoll[ym] += budget_coll_map[dept].get(ym, Decimal('0'))
            total_bpaid[ym] += budget_paid_map[dept].get(ym, Decimal('0'))

    collected_arr = [float(total_coll.get(ym, 0)) for ym in month_keys]
    paid_arr = [float(total_paid.get(ym, 0)) for ym in month_keys]
    adv_recv_arr = [float(total_adv_recv.get(ym, 0)) for ym in month_keys]
    adv_paid_arr = [float(total_adv_paid.get(ym, 0)) for ym in month_keys]
    inflow_arr = [round(collected_arr[i] + adv_recv_arr[i], 2) for i in range(len(month_keys))]
    outflow_arr = [round(paid_arr[i] + adv_paid_arr[i], 2) for i in range(len(month_keys))]
    net_arr = [round(inflow_arr[i] - outflow_arr[i], 2) for i in range(len(month_keys))]

    total_alert = [month_keys[i] for i in range(len(month_keys))
                   if outflow_arr[i] > inflow_arr[i] > 0]
    if total_alert:
        has_alert = True

    cumulative = []
    running = 0.0
    for v in net_arr:
        running += v
        cumulative.append(round(running, 2))

    return ok({
        'months': month_keys,
        'depts': depts,
        'by_dept': by_dept,
        'totals': {
            'collected': collected_arr,
            'paid': paid_arr,
            'advance_received': adv_recv_arr,
            'advance_paid': adv_paid_arr,
            'inflow': inflow_arr,
            'outflow': outflow_arr,
            'net': net_arr,
            'cumulative_net': cumulative,
            'budget_collection': [float(total_bcoll.get(ym, 0)) for ym in month_keys],
            'budget_payment': [float(total_bpaid.get(ym, 0)) for ym in month_keys],
            'alert_months': total_alert,
        },
        'has_alert': has_alert,
        'start_date': str(start_date),
        'end_date': str(end_date),
    })




# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
