"""分析域视图：账龄、回款率、欠款 Top、状态分布、按 PM/部门、单位经济性、
业财融合、项目损益、项目现金流、预测等。共享基座来自 _common。
（analytics_target_decomp 目标分解随后并入。）"""
from ._common import *  # noqa: F401,F403


# ══════════════════════════════════════════════════════════════════════════════
# Analytics
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@pk_required()
def analytics_aging(request):
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied

    today = datetime.date.today()
    eomonth_today = datetime.date(today.year, today.month,
                                  calendar.monthrange(today.year, today.month)[1])

    qs = _ar_dept_filter(
        ARRecord.objects.filter(outstanding_amount__gt=0), request,
        shared_field='project__is_shared')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    buckets = [
        ('current', '当期未到期', 0),
        ('1_30', '逾期1-30天', 1),
        ('31_60', '逾期31-60天', 2),
        ('61_90', '逾期61-90天', 3),
        ('90plus', '逾期90天以上', 4),
    ]

    result = []
    # Not overdue
    current_qs = qs.filter(due_date__gte=today)
    current_agg = current_qs.aggregate(count=Count('id'), amount=Sum('outstanding_amount'))
    result.append({'key': 'current', 'label': '当期未到期',
                   'count': current_agg['count'] or 0,
                   'amount': str(current_agg['amount'] or 0)})

    # Overdue buckets
    for key, label, _ in [('1_30', '逾期1-30天', 0), ('31_60', '逾期31-60天', 0),
                           ('61_90', '逾期61-90天', 0), ('90plus', '逾期90天以上', 0)]:
        if key == '1_30':
            bqs = qs.filter(due_date__lt=today, due_date__gte=today - datetime.timedelta(days=30))
        elif key == '31_60':
            bqs = qs.filter(due_date__lt=today - datetime.timedelta(days=30),
                            due_date__gte=today - datetime.timedelta(days=60))
        elif key == '61_90':
            bqs = qs.filter(due_date__lt=today - datetime.timedelta(days=60),
                            due_date__gte=today - datetime.timedelta(days=90))
        else:
            bqs = qs.filter(due_date__lt=today - datetime.timedelta(days=90))
        agg = bqs.aggregate(count=Count('id'), amount=Sum('outstanding_amount'))
        result.append({'key': key, 'label': label,
                       'count': agg['count'] or 0,
                       'amount': str(agg['amount'] or 0)})

    return ok(result)


@csrf_exempt
@pk_required()
def analytics_collection_rate(request):
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied

    year = _int_param(request, 'year', datetime.date.today().year)
    qs = _ar_dept_filter(ARRecord.objects.filter(operation_year=year), request,
                         shared_field='project__is_shared')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    # Estimated amounts by operation_month (billed amount entering that month)
    estimated_by_month = {}
    rec_ids = []
    for row in qs.values('id', 'operation_month', 'estimated_amount'):
        m = row['operation_month']
        estimated_by_month[m] = estimated_by_month.get(m, 0) + float(row['estimated_amount'] or 0)
        rec_ids.append(row['id'])

    # Payments by payment_date month (actual cash received in that month)
    payment_by_month = {}
    if rec_ids:
        for pay in (ARPayment.objects
                    .filter(ar_record__in=rec_ids, payment_date__year=year)
                    .values('payment_date', 'amount')):
            m = pay['payment_date'].month
            payment_by_month[m] = payment_by_month.get(m, 0) + float(pay['amount'] or 0)

    # Build monthly stats: AR base = outstanding carried from prior months + new billing
    months = []
    cumulative_outstanding = 0.0
    for m in range(1, 13):
        billed_this_month = estimated_by_month.get(m, 0.0)
        collected_this_month = payment_by_month.get(m, 0.0)
        ar_base = cumulative_outstanding + billed_this_month
        rate = (collected_this_month / ar_base * 100) if ar_base > 0 else 0.0
        cumulative_outstanding = max(0.0, ar_base - collected_this_month)
        months.append({
            'month': m,
            'receivable': round(ar_base, 2),
            'collected': round(collected_this_month, 2),
            'rate': round(min(rate, 999.99), 2),
        })

    return ok({'year': year, 'months': months})


@csrf_exempt
@pk_required()
def analytics_outstanding_top(request):
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied

    n = min(20, int(request.GET.get('n', 10)))
    qs = _ar_dept_filter(
        ARRecord.objects.filter(outstanding_amount__gt=0), request,
        shared_field='project__is_shared')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    by_project = (qs.values('project_id', 'project__project_no', 'project__short_name',
                             'project__customer_name', 'delivery_dept')
                  .annotate(total_outstanding=Sum('outstanding_amount'))
                  .order_by('-total_outstanding')[:n])

    result = []
    for r in by_project:
        result.append({
            'project_id': r['project_id'],
            'project_no': r['project__project_no'],
            'short_name': r['project__short_name'] or r['project__customer_name'],
            'delivery_dept': r['delivery_dept'],
            'total_outstanding': str(r['total_outstanding']),
        })
    return ok(result)


@csrf_exempt
@pk_required()
def analytics_status_dist(request):
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied

    today = datetime.date.today()
    eomonth_today = datetime.date(today.year, today.month,
                                  calendar.monthrange(today.year, today.month)[1])
    qs = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    total = qs.count()
    settled = qs.filter(outstanding_amount__lte=0).count()
    overdue = qs.filter(outstanding_amount__gt=0, due_date__lt=today).count()
    current = qs.filter(outstanding_amount__gt=0, due_date__gte=today,
                        due_date__lte=eomonth_today).count()
    not_due = qs.filter(outstanding_amount__gt=0, due_date__gt=eomonth_today).count()
    uninvoiced = qs.filter(actual_invoice_amount__isnull=True).count()

    # Amount aggregates
    def _sum(filter_qs):
        return str(filter_qs.aggregate(s=Sum('outstanding_amount'))['s'] or 0)

    return ok({
        'total': total,
        'settled': {'count': settled,
                    'amount': _sum(qs.filter(outstanding_amount__lte=0))},
        'overdue': {'count': overdue,
                    'amount': _sum(qs.filter(outstanding_amount__gt=0, due_date__lt=today))},
        'current': {'count': current,
                    'amount': _sum(qs.filter(outstanding_amount__gt=0, due_date__gte=today,
                                             due_date__lte=eomonth_today))},
        'not_due': {'count': not_due,
                    'amount': _sum(qs.filter(outstanding_amount__gt=0, due_date__gt=eomonth_today))},
        'uninvoiced': {'count': uninvoiced},
    })


@csrf_exempt
@pk_required()
def analytics_by_pm(request):
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied

    year = _int_param(request, 'year', datetime.date.today().year)
    qs = _ar_dept_filter(ARRecord.objects.filter(operation_year=year), request,
                         shared_field='project__is_shared')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    # 记录级金额与回款合计必须分两次聚合：payments JOIN 会让多笔回款的记录
    # 在 estimated/outstanding 求和中被乘倍（与 ar_records_group_summary 同坑同解）。
    rows = (qs.values('project__project_manager')
              .annotate(
                  estimated=Sum('estimated_amount'),
                  outstanding=Sum('outstanding_amount'),
                  project_count=Count('project_id', distinct=True),
              )
              .order_by('-outstanding'))
    paid_map = {
        g['project__project_manager']: (g['s'] or 0)
        for g in qs.values('project__project_manager').annotate(s=Sum('payments__amount'))
    }

    result = []
    for r in rows:
        pm = r['project__project_manager'] or '（未填写）'
        estimated = float(r['estimated'] or 0)
        outstanding = float(r['outstanding'] or 0)
        total_paid = float(paid_map.get(r['project__project_manager']) or 0)
        rate = (total_paid / estimated * 100) if estimated > 0 else 0.0
        result.append({
            'pm': pm,
            'project_count': r['project_count'],
            'estimated': round(estimated, 2),
            'outstanding': round(outstanding, 2),
            'collected': round(total_paid, 2),
            'rate': round(min(max(rate, 0), 999.99), 2),
        })
    return ok(result)


_UE_UNLINKED = '未关联客户'


@csrf_exempt
@pk_required()
def analytics_unit_economics(request):
    """客户/项目 单位经济学：客单价 / 客单成本 / 边际贡献。

    口径：收入与成本均取自 caiwu「项目毛利表」(ProjectMargin，金蝶核算维度)，
    边际贡献 = 收入 − 主营成本；客户归属经 ARProject(短名/合同名) 映射。
    入参：year(必填) month(可选,缺省=全年累计) dept(可选) group_by=project|customer
    """
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    try:
        year = int(request.GET.get('year') or datetime.date.today().year)
    except (TypeError, ValueError):
        return err('年份无效')
    month = None
    month_raw = (request.GET.get('month') or '').strip()
    if month_raw:
        try:
            month = int(month_raw)
            assert 1 <= month <= 12
        except Exception:
            return err('月份无效')
    group_by = (request.GET.get('group_by') or 'project').strip()
    if group_by not in ('project', 'customer'):
        group_by = 'project'
    dept = (request.GET.get('dept') or '').strip()

    from caiwu.models import ProjectMargin
    pm = ProjectMargin.objects.filter(year=year)
    if month:
        pm = pm.filter(month=month)
    if dept:
        pm = pm.filter(business_unit=dept)
    pm = _ar_dept_filter(pm, request, dept_field='business_unit')

    # 聚合到项目（跨月/跨录入求和），business_unit 取贡献最大者
    proj_agg = {}
    for r in pm.values('project_name', 'business_unit').annotate(
            revenue=Sum('revenue'), cost=Sum('cost'),
            sales_exp=Sum('sales_exp'), mgmt_exp=Sum('mgmt_exp')):
        name = (r['project_name'] or '').strip() or '（未命名项目）'
        rev = float(r['revenue'] or 0)
        a = proj_agg.get(name)
        if a is None:
            a = proj_agg[name] = {'project_name': name, 'business_unit': r['business_unit'],
                                  'revenue': 0.0, 'cost': 0.0, 'sales_exp': 0.0, 'mgmt_exp': 0.0,
                                  '_bu_rev': 0.0}
        if rev > a['_bu_rev']:
            a['business_unit'] = r['business_unit']
            a['_bu_rev'] = rev
        a['revenue'] += rev
        a['cost'] += float(r['cost'] or 0)
        a['sales_exp'] += float(r['sales_exp'] or 0)
        a['mgmt_exp'] += float(r['mgmt_exp'] or 0)

    # 客户映射：ProjectMargin.project_name ←→ ARProject.short_name / customer_name
    aqs = ARProject.objects.all()
    if request.pk_role != 'super_admin':
        aqs = aqs.filter(delivery_dept__in=(request.pk_depts or []))
    name_to_cust = {}
    for p in aqs.select_related('customer').only(
            'short_name', 'customer_name', 'customer_level', 'delivery_dept', 'customer'):
        info = {'customer': (p.customer.name if p.customer_id else None),
                'level': p.customer_level or '', 'dept': p.delivery_dept or ''}
        for k in (p.short_name, p.customer_name):
            k = (k or '').strip()
            if k and k not in name_to_cust:
                name_to_cust[k] = info

    projects = []
    for a in proj_agg.values():
        info = name_to_cust.get(a['project_name'])
        cust = (info['customer'] if info else None) or _UE_UNLINKED
        rev, cost = a['revenue'], a['cost']
        margin = rev - cost
        projects.append({
            'key': a['project_name'], 'label': a['project_name'],
            'project_name': a['project_name'], 'business_unit': a['business_unit'],
            'customer': cust, 'customer_level': (info['level'] if info else ''),
            'revenue': round(rev, 2), 'cost': round(cost, 2),
            'sales_exp': round(a['sales_exp'], 2), 'mgmt_exp': round(a['mgmt_exp'], 2),
            'margin': round(margin, 2),
            'margin_rate': round(margin / rev * 100, 2) if rev else None,
        })

    # 客户聚合
    cust_agg = {}
    for p in projects:
        c = p['customer']
        d = cust_agg.get(c)
        if d is None:
            d = cust_agg[c] = {'customer': c, 'level': p['customer_level'],
                               'revenue': 0.0, 'cost': 0.0, 'margin': 0.0, 'project_count': 0}
        d['revenue'] += p['revenue']
        d['cost'] += p['cost']
        d['margin'] += p['margin']
        d['project_count'] += 1
        if not d['level'] and p['customer_level']:
            d['level'] = p['customer_level']

    tot_rev = round(sum(p['revenue'] for p in projects), 2)
    tot_cost = round(sum(p['cost'] for p in projects), 2)
    tot_margin = round(tot_rev - tot_cost, 2)
    real = [d for c, d in cust_agg.items() if c != _UE_UNLINKED]
    cc = len(real)
    linked_rev = sum(d['revenue'] for d in real)
    linked_cost = sum(d['cost'] for d in real)
    linked_margin = sum(d['margin'] for d in real)

    summary = {
        'revenue': tot_rev, 'cost': tot_cost, 'margin': tot_margin,
        'margin_rate': round(tot_margin / tot_rev * 100, 2) if tot_rev else None,
        'project_count': len(projects),
        'customer_count': cc,
        'arpu': round(linked_rev / cc, 2) if cc else None,           # 客单价
        'acpu': round(linked_cost / cc, 2) if cc else None,          # 客单成本
        'margin_per_customer': round(linked_margin / cc, 2) if cc else None,  # 客均边际贡献
        'linked_coverage': round(linked_rev / tot_rev * 100, 1) if tot_rev else None,
    }

    if group_by == 'customer':
        rows = []
        for d in cust_agg.values():
            rev, margin = d['revenue'], d['margin']
            rows.append({
                'key': d['customer'], 'label': d['customer'], 'customer_level': d['level'],
                'revenue': round(rev, 2), 'cost': round(d['cost'], 2), 'margin': round(margin, 2),
                'margin_rate': round(margin / rev * 100, 2) if rev else None,
                'project_count': d['project_count'], 'unlinked': d['customer'] == _UE_UNLINKED,
            })
        rows.sort(key=lambda x: x['margin'], reverse=True)
    else:
        rows = sorted(projects, key=lambda x: x['margin'], reverse=True)

    return ok({'year': year, 'month': month, 'group_by': group_by,
               'rows': rows, 'summary': summary})


# ── 业财损益全景：财务侧毛利 × 应收侧回款，融合在同一项目/客户维度 ──────────────
def _bf_tag(margin_rate, collect_rate, overdue_rate, revenue):
    """给每个项目/客户打一个"业财融合"标签，一眼看穿盈利与回款的错配。
    口径阈值：毛利率<5% 视为薄利；逾期占比>30% 或 回款率<60% 视为回款承压。"""
    thin_margin = margin_rate is not None and margin_rate < 5
    weak_cash = (overdue_rate is not None and overdue_rate > 30) or \
                (collect_rate is not None and collect_rate < 60)
    if revenue is not None and revenue <= 0:
        return ('idle', '无收入')
    if thin_margin and weak_cash:
        return ('critical', '又薄又难收')          # 红牌：低毛利 + 回款差
    if thin_margin:
        return ('low_margin', '赚收入不赚钱')        # 黄牌：规模大但薄利
    if weak_cash:
        return ('cash_risk', '赚利润收不回钱')        # 黄牌：有毛利但回款承压
    return ('healthy', '优质')                       # 绿牌：双优


@csrf_exempt
@pk_required()
def analytics_business_finance(request):
    """业财损益全景：把财务侧「项目毛利」(ProjectMargin) 与应收侧「回款/账期」
    (ARRecord/ARPayment) 嫁接在同一项目/客户维度，一眼识别两类隐性风险——
    「赚收入不赚钱」(薄利) 与「赚利润收不回钱」(回款承压)。

    入参：year(必填) month(可选,缺省=全年累计) dept(可选) group_by=project|customer
    返回 rows：每行含 盈利侧(revenue/cost/margin/margin_rate) +
              应收侧(estimated/invoiced/outstanding/collected/collect_rate/overdue/overdue_rate)
              + 融合标签(tag/tag_label)；外加 summary。
    """
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    try:
        year = int(request.GET.get('year') or datetime.date.today().year)
    except (TypeError, ValueError):
        return err('年份无效')
    month = None
    month_raw = (request.GET.get('month') or '').strip()
    if month_raw:
        try:
            month = int(month_raw)
            assert 1 <= month <= 12
        except Exception:
            return err('月份无效')
    group_by = (request.GET.get('group_by') or 'project').strip()
    if group_by not in ('project', 'customer'):
        group_by = 'project'
    dept = (request.GET.get('dept') or '').strip()
    today = datetime.date.today()

    # ── 盈利侧：ProjectMargin 按项目聚合（沿用 unit-economics 口径）──────────────
    from caiwu.models import ProjectMargin
    pm = ProjectMargin.objects.filter(year=year)
    if month:
        pm = pm.filter(month=month)
    if dept:
        pm = pm.filter(business_unit=dept)
    pm = _ar_dept_filter(pm, request, dept_field='business_unit')
    proj_fin = {}
    for r in pm.values('project_name').annotate(revenue=Sum('revenue'), cost=Sum('cost')):
        name = (r['project_name'] or '').strip() or '（未命名项目）'
        a = proj_fin.setdefault(name, {'revenue': 0.0, 'cost': 0.0})
        a['revenue'] += float(r['revenue'] or 0)
        a['cost'] += float(r['cost'] or 0)

    # ── 项目名 → ARProject(身份+客户) 映射，并保留 project_id 反查应收 ────────────
    aqs = ARProject.objects.all()
    if request.pk_role != 'super_admin':
        aqs = aqs.filter(delivery_dept__in=(request.pk_depts or []))
    name_to_proj = {}
    for p in aqs.select_related('customer').only(
            'id', 'short_name', 'customer_name', 'customer_level', 'delivery_dept', 'customer'):
        info = {'pid': p.id, 'customer': (p.customer.name if p.customer_id else None),
                'level': p.customer_level or '', 'dept': p.delivery_dept or ''}
        for k in (p.short_name, p.customer_name):
            k = (k or '').strip()
            if k and k not in name_to_proj:
                name_to_proj[k] = info

    # ── 应收侧：ARRecord 按项目聚合（避免 payments JOIN 扇出，回款单独查）──────────
    ar_qs = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
    ar_qs = ar_qs.filter(operation_year=year)
    if month:
        ar_qs = ar_qs.filter(operation_month=month)
    if dept:
        ar_qs = ar_qs.filter(delivery_dept=dept)
    ar_by_pid = {}
    for r in ar_qs.values('project_id').annotate(
            estimated=Sum('estimated_amount'), invoiced=Sum('actual_invoice_amount'),
            outstanding=Sum('outstanding_amount')):
        ar_by_pid[r['project_id']] = {
            'estimated': float(r['estimated'] or 0), 'invoiced': float(r['invoiced'] or 0),
            'outstanding': float(r['outstanding'] or 0), 'collected': 0.0, 'overdue': 0.0}
    # 逾期未收：已过应收日且仍有余额
    for r in ar_qs.filter(due_date__lt=today, outstanding_amount__gt=0).values(
            'project_id').annotate(overdue=Sum('outstanding_amount')):
        if r['project_id'] in ar_by_pid:
            ar_by_pid[r['project_id']]['overdue'] = float(r['overdue'] or 0)
    # 已回款：单独从 ARPayment 聚合，规避反向 JOIN 重复求和
    for r in ARPayment.objects.filter(ar_record__in=ar_qs).values(
            'ar_record__project_id').annotate(collected=Sum('amount')):
        pid = r['ar_record__project_id']
        if pid in ar_by_pid:
            ar_by_pid[pid]['collected'] = float(r['collected'] or 0)

    # ── 融合：以盈利侧项目为主线，并接应收侧 ──────────────────────────────────────
    def _rate(num, den):
        return round(num / den * 100, 1) if den else None

    projects = []
    for name, fin in proj_fin.items():
        info = name_to_proj.get(name)
        ar = ar_by_pid.get(info['pid']) if info else None
        rev, cost = fin['revenue'], fin['cost']
        margin = rev - cost
        mr = _rate(margin, rev)
        est = ar['estimated'] if ar else 0.0
        inv = ar['invoiced'] if ar else 0.0
        out = ar['outstanding'] if ar else 0.0
        col = ar['collected'] if ar else 0.0
        ovd = ar['overdue'] if ar else 0.0
        cr = _rate(col, inv) if inv else None          # 回款率 = 已收/已开票
        ovr = _rate(ovd, out) if out else None          # 逾期占比 = 逾期/未收
        tag, tag_label = _bf_tag(mr, cr, ovr, rev)
        projects.append({
            'key': name, 'label': name, 'project_name': name,
            'business_unit': (info['dept'] if info else ''),
            'customer': (info['customer'] if info else None) or _UE_UNLINKED,
            'customer_level': (info['level'] if info else ''),
            'linked': bool(ar),
            'revenue': round(rev, 2), 'cost': round(cost, 2),
            'margin': round(margin, 2), 'margin_rate': mr,
            'estimated': round(est, 2), 'invoiced': round(inv, 2),
            'outstanding': round(out, 2), 'collected': round(col, 2),
            'collect_rate': cr, 'overdue': round(ovd, 2), 'overdue_rate': ovr,
            'tag': tag, 'tag_label': tag_label,
        })

    # ── 客户聚合 ────────────────────────────────────────────────────────────────
    cust_agg = {}
    for p in projects:
        c = p['customer']
        d = cust_agg.get(c)
        if d is None:
            d = cust_agg[c] = {'customer': c, 'level': p['customer_level'], 'project_count': 0,
                               'revenue': 0.0, 'cost': 0.0, 'margin': 0.0,
                               'invoiced': 0.0, 'outstanding': 0.0, 'collected': 0.0, 'overdue': 0.0}
        for k in ('revenue', 'cost', 'margin', 'invoiced', 'outstanding', 'collected', 'overdue'):
            d[k] += p[k]
        d['project_count'] += 1
        if not d['level'] and p['customer_level']:
            d['level'] = p['customer_level']

    def _pack_customer(d):
        rev, margin = d['revenue'], d['margin']
        mr = _rate(margin, rev)
        cr = _rate(d['collected'], d['invoiced']) if d['invoiced'] else None
        ovr = _rate(d['overdue'], d['outstanding']) if d['outstanding'] else None
        tag, tag_label = _bf_tag(mr, cr, ovr, rev)
        return {
            'key': d['customer'], 'label': d['customer'], 'customer_level': d['level'],
            'project_count': d['project_count'], 'unlinked': d['customer'] == _UE_UNLINKED,
            'revenue': round(rev, 2), 'cost': round(d['cost'], 2),
            'margin': round(margin, 2), 'margin_rate': mr,
            'invoiced': round(d['invoiced'], 2), 'outstanding': round(d['outstanding'], 2),
            'collected': round(d['collected'], 2), 'collect_rate': cr,
            'overdue': round(d['overdue'], 2), 'overdue_rate': ovr,
            'tag': tag, 'tag_label': tag_label,
        }

    # ── 汇总 ────────────────────────────────────────────────────────────────────
    tot_rev = round(sum(p['revenue'] for p in projects), 2)
    tot_cost = round(sum(p['cost'] for p in projects), 2)
    tot_margin = round(tot_rev - tot_cost, 2)
    tot_inv = round(sum(p['invoiced'] for p in projects), 2)
    tot_out = round(sum(p['outstanding'] for p in projects), 2)
    tot_col = round(sum(p['collected'] for p in projects), 2)
    tot_ovd = round(sum(p['overdue'] for p in projects), 2)
    by_tag = {}
    for p in projects:
        t = by_tag.setdefault(p['tag'], {'count': 0, 'revenue': 0.0, 'margin': 0.0, 'overdue': 0.0})
        t['count'] += 1
        t['revenue'] += p['revenue']
        t['margin'] += p['margin']
        t['overdue'] += p['overdue']
    summary = {
        'revenue': tot_rev, 'cost': tot_cost, 'margin': tot_margin,
        'margin_rate': _rate(tot_margin, tot_rev),
        'invoiced': tot_inv, 'outstanding': tot_out, 'collected': tot_col, 'overdue': tot_ovd,
        'collect_rate': _rate(tot_col, tot_inv), 'overdue_rate': _rate(tot_ovd, tot_out),
        'project_count': len(projects),
        'linked_count': sum(1 for p in projects if p['linked']),
        'by_tag': {k: {'count': v['count'], 'revenue': round(v['revenue'], 2),
                       'margin': round(v['margin'], 2), 'overdue': round(v['overdue'], 2)}
                   for k, v in by_tag.items()},
    }

    if group_by == 'customer':
        rows = [_pack_customer(d) for d in cust_agg.values()]
        rows.sort(key=lambda x: x['margin'], reverse=True)
    else:
        rows = sorted(projects, key=lambda x: x['revenue'], reverse=True)

    return ok({'year': year, 'month': month, 'group_by': group_by,
               'rows': rows, 'summary': summary})


@csrf_exempt
@pk_required()
def analytics_project_pnl(request):
    """单项目业财损益卡：一个项目从「合同→开票→回款→毛利」的全链路。
    盈利侧逐月取自 ProjectMargin，应收侧逐月取自 ARRecord/ARPayment。
    入参：name(项目名,必填) year(必填)。返回 project/monthly/payments/totals。
    """
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    name = (request.GET.get('name') or '').strip()
    if not name:
        return err('缺少项目名')
    try:
        year = int(request.GET.get('year') or datetime.date.today().year)
    except (TypeError, ValueError):
        return err('年份无效')
    today = datetime.date.today()

    # ── 盈利侧：ProjectMargin 按月 ──────────────────────────────────────────────
    from caiwu.models import ProjectMargin
    pm = _ar_dept_filter(ProjectMargin.objects.filter(year=year, project_name=name),
                         request, dept_field='business_unit')
    fin_by_m = {}
    for r in pm.values('month').annotate(revenue=Sum('revenue'), cost=Sum('cost'),
                                         sales_exp=Sum('sales_exp'), mgmt_exp=Sum('mgmt_exp')):
        fin_by_m[r['month']] = {'revenue': float(r['revenue'] or 0), 'cost': float(r['cost'] or 0),
                                'sales_exp': float(r['sales_exp'] or 0), 'mgmt_exp': float(r['mgmt_exp'] or 0)}

    # ── 项目身份：name → ARProject（短名或合同名匹配）──────────────────────────
    aqs = ARProject.objects.select_related('customer')
    if request.pk_role != 'super_admin':
        aqs = aqs.filter(delivery_dept__in=(request.pk_depts or []))
    projs = list(aqs.filter(Q(short_name=name) | Q(customer_name=name)))
    proj = projs[0] if projs else None
    pids = [p.id for p in projs]

    # ── 应收侧：ARRecord 按月（回款单独从 ARPayment 取，规避扇出）────────────────
    ar_by_m = {}
    arq = ARRecord.objects.none()
    if pids:
        arq = ARRecord.objects.filter(project_id__in=pids, operation_year=year)
        for r in arq.values('operation_month').annotate(
                estimated=Sum('estimated_amount'), invoiced=Sum('actual_invoice_amount'),
                outstanding=Sum('outstanding_amount'), tax=Sum('tax_amount')):
            ar_by_m[r['operation_month']] = {
                'estimated': float(r['estimated'] or 0), 'invoiced': float(r['invoiced'] or 0),
                'outstanding': float(r['outstanding'] or 0), 'tax': float(r['tax'] or 0),
                'collected': 0.0, 'overdue': 0.0}
        for r in arq.filter(due_date__lt=today, outstanding_amount__gt=0).values(
                'operation_month').annotate(overdue=Sum('outstanding_amount')):
            if r['operation_month'] in ar_by_m:
                ar_by_m[r['operation_month']]['overdue'] = float(r['overdue'] or 0)
        for r in ARPayment.objects.filter(ar_record__in=arq).values(
                'ar_record__operation_month').annotate(c=Sum('amount')):
            m = r['ar_record__operation_month']
            if m in ar_by_m:
                ar_by_m[m]['collected'] = float(r['c'] or 0)

    # ── 逐月融合 ────────────────────────────────────────────────────────────────
    def _rate(num, den):
        return round(num / den * 100, 1) if den else None
    monthly = []
    for m in sorted(set(fin_by_m) | set(ar_by_m)):
        f = fin_by_m.get(m, {})
        a = ar_by_m.get(m, {})
        rev, cost = f.get('revenue', 0.0), f.get('cost', 0.0)
        monthly.append({
            'month': m, 'revenue': round(rev, 2), 'cost': round(cost, 2),
            'margin': round(rev - cost, 2), 'margin_rate': _rate(rev - cost, rev),
            'invoiced': round(a.get('invoiced', 0.0), 2), 'outstanding': round(a.get('outstanding', 0.0), 2),
            'collected': round(a.get('collected', 0.0), 2), 'overdue': round(a.get('overdue', 0.0), 2),
        })

    # ── 回款流水（时间线）──────────────────────────────────────────────────────
    payments = []
    if pids:
        for pay in (ARPayment.objects.filter(ar_record__in=arq)
                    .select_related('ar_record').order_by('payment_date', 'id')[:200]):
            payments.append({
                'date': str(pay.payment_date) if pay.payment_date else None,
                'amount': float(pay.amount or 0), 'source': pay.source or '回款',
                'operation_month': pay.ar_record.operation_month})

    # ── 汇总 + 标签 ────────────────────────────────────────────────────────────
    t_rev = round(sum(x['revenue'] for x in monthly), 2)
    t_cost = round(sum(x['cost'] for x in monthly), 2)
    t_margin = round(t_rev - t_cost, 2)
    t_inv = round(sum(x['invoiced'] for x in monthly), 2)
    t_out = round(sum(x['outstanding'] for x in monthly), 2)
    t_col = round(sum(x['collected'] for x in monthly), 2)
    t_ovd = round(sum(x['overdue'] for x in monthly), 2)
    mr = _rate(t_margin, t_rev)
    cr = _rate(t_col, t_inv)
    ovr = _rate(t_ovd, t_out)
    tag, tag_label = _bf_tag(mr, cr, ovr, t_rev)
    totals = {'revenue': t_rev, 'cost': t_cost, 'margin': t_margin, 'margin_rate': mr,
              'invoiced': t_inv, 'outstanding': t_out, 'collected': t_col, 'collect_rate': cr,
              'overdue': t_ovd, 'overdue_rate': ovr, 'tag': tag, 'tag_label': tag_label}

    # ── 付款侧（排款台账，经「项目简称/项目编号」打通）─────────────────────────
    # 排款新增 project_short_name 字段后，项目维度可闭环：回款（流入）对照
    # 排款付款（流出），得到项目净现金。仅匹配非空键，防止空串误匹配全表。
    payment_side = None
    if proj:
        cond = Q()
        if proj.short_name:
            cond |= Q(project_short_name=proj.short_name)
        if proj.project_no:
            cond |= Q(project_no=proj.project_no)
        if cond:
            pq = Payment.objects.filter(cond)
            if request.pk_role != 'super_admin':
                pq = pq.filter(department__in=(request.pk_depts or []))
            agg = pq.annotate(paid_sum=_paid_subq()).aggregate(
                planned=Sum(Coalesce('plan_adjustment', 'total_amount')),
                paid=Sum('paid_sum'), offset=Sum('prepaid_offset_amount'), n=Count('id'))
            planned = float(agg['planned'] or 0)
            paid = float(agg['paid'] or 0)
            offset = float(agg['offset'] or 0)
            payment_side = {
                'count': agg['n'] or 0,
                'planned': round(planned, 2),
                'paid': round(paid, 2),
                'prepaid_offset': round(offset, 2),
                'remaining': round(max(0.0, planned - paid - offset), 2),
                'net_cash': round(t_col - paid, 2),
            }

    project = {
        'name': name,
        'project_no': (proj.project_no if proj else None),
        'short_name': (proj.short_name if proj else name),
        'customer_name': (proj.customer_name if proj else None),
        'customer': (proj.customer.name if (proj and proj.customer_id) else None),
        'customer_level': (proj.customer_level if proj else ''),
        'delivery_dept': (proj.delivery_dept if proj else ''),
        'project_manager': (proj.project_manager if proj else ''),
        'sales_contact': (proj.sales_contact if proj else ''),
        'has_contract': (proj.has_contract if proj else ''),
        'contract_date': (str(proj.contract_date) if (proj and proj.contract_date) else None),
        'total_days': (proj.total_days if proj else None),
        'linked': bool(pids),
    }
    return ok({'year': year, 'project': project, 'monthly': monthly,
               'payments': payments, 'totals': totals, 'payment_side': payment_side})


# ── 现金流多维聚合的维度注册表 ─────────────────────────────────────────────────
# 应收侧键：ARRecord/ARPayment 经 project 关联取值；付款侧键：Payment 自身字段。
# 新增维度（如客户、负责人）只需在两侧模型补字段后在此登记，前端维度切换即生效。
_CASHFLOW_DIMS = {
    'project': {
        'ar_rec_key': 'project__short_name',
        'ar_pay_key': 'ar_record__project__short_name',
        'pk_key': 'payment__project_short_name',
        'label': '项目',
    },
    'secondary_dept': {
        'ar_rec_key': 'project__sub_dept',
        'ar_pay_key': 'ar_record__project__sub_dept',
        'pk_key': 'payment__secondary_dept',
        'label': '二级部门',
    },
}


@csrf_exempt
@pk_required()
def analytics_project_cashflow(request):
    """现金流多维聚合：按维度（项目简称/二级部门）聚合区间内回款（流入）、
    排款付款（流出）、应收敞口（未收）。
    入参：group_by(project|secondary_dept,默认project), dept(可选),
          year(默认今年), date_start/date_end(可选，优先级高于year)
    返回：按净现金降序排列的维度成员列表 + 汇总。"""
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    dept = (request.GET.get('dept') or '').strip()
    group_by = (request.GET.get('group_by') or 'project').strip()
    dim = _CASHFLOW_DIMS.get(group_by) or _CASHFLOW_DIMS['project']
    if group_by not in _CASHFLOW_DIMS:
        group_by = 'project'
    try:
        year = int(request.GET.get('year') or datetime.date.today().year)
    except (TypeError, ValueError):
        year = datetime.date.today().year

    # Date range: explicit start/end overrides year-based default
    _ds_raw = _normalize_date(request.GET.get('date_start'))
    _de_raw = _normalize_date(request.GET.get('date_end'))
    try:
        date_start = datetime.date.fromisoformat(_ds_raw) if _ds_raw else datetime.date(year, 1, 1)
        date_end = datetime.date.fromisoformat(_de_raw) if _de_raw else datetime.date(year, 12, 31)
    except (ValueError, AttributeError):
        date_start, date_end = datetime.date(year, 1, 1), datetime.date(year, 12, 31)

    rec_key, arp_key, pk_key = dim['ar_rec_key'], dim['ar_pay_key'], dim['pk_key']

    # ── 应收侧 base queryset ──────────────────────────────────────────────────
    ar_base = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
    if dept:
        ar_base = ar_base.filter(delivery_dept=dept)

    # 当前应收敞口（全周期，当前余额；按维度键聚合）
    outstanding_by_key = {}
    for r in (ar_base
              .filter(**{f'{rec_key}__isnull': False})
              .exclude(**{rec_key: ''})
              .values(rec_key, 'delivery_dept')
              .annotate(outstanding=Sum('outstanding_amount'), estimated=Sum('estimated_amount'))):
        key = r[rec_key]
        if key not in outstanding_by_key:
            outstanding_by_key[key] = {'outstanding': 0.0, 'estimated': 0.0, 'dept': r['delivery_dept'] or ''}
        outstanding_by_key[key]['outstanding'] += float(r['outstanding'] or 0)
        outstanding_by_key[key]['estimated'] += float(r['estimated'] or 0)

    # 区间内回款（流入）
    inflow_by_key = {}
    for r in (ARPayment.objects
              .filter(ar_record__in=ar_base,
                      payment_date__gte=date_start,
                      payment_date__lte=date_end)
              .filter(**{f'{arp_key}__isnull': False})
              .exclude(**{arp_key: ''})
              .values(arp_key)
              .annotate(total=Sum('amount'))):
        inflow_by_key[r[arp_key]] = float(r['total'] or 0)

    # 区间内付款（流出）：PaymentInstallment 按维度键聚合
    outflow_by_key = {}
    pi_base = PaymentInstallment.objects.filter(pay_date__gte=date_start, pay_date__lte=date_end)
    if request.pk_role != 'super_admin':
        pi_base = pi_base.filter(payment__department__in=(request.pk_depts or []))
    if dept:
        pi_base = pi_base.filter(payment__department=dept)
    pi_base = pi_base.exclude(**{pk_key: ''})
    for r in pi_base.values(pk_key).annotate(total=Sum('pay_amount')):
        outflow_by_key[r[pk_key]] = float(r['total'] or 0)

    # ── 合并所有维度成员 ──────────────────────────────────────────────────────
    all_names = set(outstanding_by_key) | set(inflow_by_key) | set(outflow_by_key)
    proj_meta = {}
    if group_by == 'project' and all_names:
        for p in ARProject.objects.filter(short_name__in=list(all_names)):
            proj_meta[p.short_name] = {
                'dept': p.delivery_dept or '',
                'project_no': p.project_no or '',
                'customer': p.customer_name or '',
                'manager': p.project_manager or '',
            }

    rows = []
    for name in all_names:
        meta = proj_meta.get(name, {})
        row_dept = meta.get('dept') or outstanding_by_key.get(name, {}).get('dept', '')
        # If dept filter active and this member doesn't match, skip
        if dept and row_dept and row_dept != dept:
            continue
        inflow = inflow_by_key.get(name, 0.0)
        outflow = outflow_by_key.get(name, 0.0)
        out_info = outstanding_by_key.get(name, {})
        rows.append({
            'project': name,            # 维度成员名（project 维=项目简称，secondary_dept 维=二级部门名）
            'dept': row_dept,
            'project_no': meta.get('project_no', ''),
            'customer': meta.get('customer', ''),
            'manager': meta.get('manager', ''),
            'inflow': round(inflow, 2),
            'outflow': round(outflow, 2),
            'net': round(inflow - outflow, 2),
            'outstanding': round(out_info.get('outstanding', 0.0), 2),
            'estimated': round(out_info.get('estimated', 0.0), 2),
        })

    rows.sort(key=lambda x: x['net'], reverse=True)
    total_in = round(sum(r['inflow'] for r in rows), 2)
    total_out = round(sum(r['outflow'] for r in rows), 2)
    return ok({
        'rows': rows,
        'year': year,
        'group_by': group_by,
        'group_label': dim['label'],
        'date_start': str(date_start),
        'date_end': str(date_end),
        'summary': {
            'inflow': total_in,
            'outflow': total_out,
            'net': round(total_in - total_out, 2),
            'outstanding': round(sum(r['outstanding'] for r in rows), 2),
            'count': len(rows),
        },
    })


@csrf_exempt
@pk_required()
def analytics_forecast(request):
    """判未来：①现金流入预测（应收账龄 + 历史回款滞后）②全年落地预测（YTD 年化 vs
    年度目标）③What-if 沙盘基线。入参：year(必填) dept(可选) horizon(默认6,3~12)。"""
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    try:
        year = int(request.GET.get('year') or datetime.date.today().year)
    except (TypeError, ValueError):
        return err('年份无效')
    dept = (request.GET.get('dept') or '').strip()
    try:
        horizon = min(max(int(request.GET.get('horizon') or 6), 3), 12)
    except (TypeError, ValueError):
        horizon = 6
    today = datetime.date.today()

    base = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
    if dept:
        base = base.filter(delivery_dept=dept)

    # ── 历史回款滞后：实付日 − 应收日 的中位天数（仅用真实回款样本）──────────────
    lag_samples = []
    for p in (ARPayment.objects.filter(source='回款', ar_record__in=base,
                                       ar_record__due_date__isnull=False, payment_date__isnull=False)
              .values('payment_date', 'ar_record__due_date')[:5000]):
        lag_samples.append((p['payment_date'] - p['ar_record__due_date']).days)
    lag_samples.sort()
    avg_lag = lag_samples[len(lag_samples) // 2] if lag_samples else 30
    avg_lag = max(0, min(avg_lag, 120))

    # ── 现金流入预测：未收记录按"应收日+滞后"的预计回款月归集 ────────────────────
    cur = datetime.date(today.year, today.month, 1)
    months, y, m = [], today.year, today.month
    for _ in range(horizon):
        months.append(f'{y:04d}-{m:02d}')
        m += 1
        if m > 12:
            m, y = 1, y + 1
    bucket = {k: 0.0 for k in months}
    opening = beyond = baddebt = 0.0
    for r in base.filter(outstanding_amount__gt=0, due_date__isnull=False).values('due_date', 'outstanding_amount'):
        amt = float(r['outstanding_amount'] or 0)
        opening += amt
        due = r['due_date']
        if due < today and (today - due).days > 90:
            baddebt += amt
        exp = due + datetime.timedelta(days=avg_lag)
        key = f'{exp.year:04d}-{exp.month:02d}'
        if exp < cur:
            bucket[months[0]] += amt        # 预计回款日已过 → 计入首月回收
        elif key in bucket:
            bucket[key] += amt
        else:
            beyond += amt                    # 超出预测窗口（远期）
    cum, cash_rows = 0.0, []
    for k in months:
        cum += bucket[k]
        cash_rows.append({'month': k, 'expected': round(bucket[k], 2), 'cumulative': round(cum, 2)})

    # ── 全年落地预测：YTD 年化 vs 年度目标（财务口径）────────────────────────────
    from caiwu import views as V
    if dept:
        fin_bus = [dept]
    elif request.pk_role == 'super_admin':
        fin_bus = list(DEPARTMENTS)
    else:
        fin_bus = list(request.pk_depts or [])
    actuals = V._collect_actuals(fin_bus, {year})
    mdata = [mm for mm in range(1, 13) if V._period_group(actuals, fin_bus, year, mm)[0] is not None]
    elapsed = len(mdata)
    ytd_rev = V._sum_opt([V._period_group(actuals, fin_bus, year, mm)[0] for mm in mdata]) or 0
    ytd_prof = V._sum_opt([V._period_group(actuals, fin_bus, year, mm)[1] for mm in mdata]) or 0
    ytd_gross = V._sum_opt([V._period_group(actuals, fin_bus, year, mm)[2] for mm in mdata]) or 0
    tgt = V._load_target_index(fin_bus, year)
    ann_t = {k: sum(tgt.get((b, 0), {}).get(k, 0) for b in fin_bus)
             for k in ('target_revenue', 'target_profit', 'target_gross_profit')}

    def _pace(ytd, target):
        proj = (ytd / elapsed * 12) if elapsed else 0
        return {'ytd': round(ytd, 2), 'projected': round(proj, 2), 'target': round(target, 2),
                'rate': round(proj / target * 100, 1) if target else None,
                'gap': round(proj - target, 2)}
    landing = {'elapsed': elapsed,
               'revenue': _pace(ytd_rev, ann_t['target_revenue']),
               'gross': _pace(ytd_gross, ann_t['target_gross_profit']),
               'profit': _pace(ytd_prof, ann_t['target_profit'])}

    proj_rev = (ytd_rev / elapsed * 12) if elapsed else 0
    proj_prof = (ytd_prof / elapsed * 12) if elapsed else 0
    baseline = {
        'proj_revenue': round(proj_rev, 2),
        'gross_margin': round(ytd_gross / ytd_rev * 100, 2) if ytd_rev else None,
        'net_margin': round(ytd_prof / ytd_rev * 100, 2) if ytd_rev else None,
        'outstanding': round(opening, 2), 'avg_lag_days': avg_lag,
        'window_total': round(cum, 2), 'horizon': horizon,
    }
    summary = {
        'proj_profit': round(proj_prof, 2), 'profit_target': round(ann_t['target_profit'], 2),
        'profit_gap': round(proj_prof - ann_t['target_profit'], 2),
        'profit_rate': landing['profit']['rate'],
        'revenue_rate': landing['revenue']['rate'],
        'cash_next3': round(sum(x['expected'] for x in cash_rows[:3]), 2),
        'opening_outstanding': round(opening, 2), 'baddebt_risk': round(baddebt, 2),
        'avg_lag_days': avg_lag,
    }
    return ok({'year': year, 'dept': dept or None, 'horizon': horizon, 'avg_lag_days': avg_lag,
               'cash': {'opening_outstanding': round(opening, 2), 'months': cash_rows,
                        'expected_window_total': round(cum, 2), 'beyond_window': round(beyond, 2),
                        'baddebt_risk': round(baddebt, 2)},
               'landing': landing, 'baseline': baseline, 'summary': summary})


@csrf_exempt
@pk_required()
def analytics_by_dept(request):
    """事业部应收全景：各事业部 上账/开票/已收/未收/逾期/回款率/本月到期目标。

    口径：开放 AR 快照（不按年筛，反映当前应收健康）。本月到期目标 = 当期(本月到期
    且未结清) + 逾期(已过期且未结清) 的上账金额，对应"该月各事业部当期+逾期上账"。
    全集团口径下返回全部可访问事业部（含零值），逐一体现 6 事业部维度。
    """
    denied = _page_denied(request, 'ar_analytics')
    if denied:
        return denied
    today = datetime.date.today()
    month_start = today.replace(day=1)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    base = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
    dept = (request.GET.get('dept') or '').strip()
    if dept:
        base = base.filter(delivery_dept=dept)

    # 展示用事业部清单（即使无数据也列出，体现全部事业部维度）
    if dept:
        dept_list = [dept]
    elif request.pk_role == 'super_admin':
        dept_list = list(DEPARTMENTS)
    else:
        dept_list = list(request.pk_depts or [])

    def _bydept(qs, **ann):
        return {r['delivery_dept']: r for r in qs.values('delivery_dept').annotate(**ann)}

    # collected 单独聚合：与记录级 Sum 同窗会因 payments JOIN 行扇出乘倍记录级金额
    overall = _bydept(base, estimated=Sum('estimated_amount'), invoiced=Sum('actual_invoice_amount'),
                      outstanding=Sum('outstanding_amount'),
                      cnt=Count('id', distinct=True))
    collected_by_dept = _bydept(base, collected=Sum('payments__amount'))
    for d, row in overall.items():
        row['collected'] = (collected_by_dept.get(d) or {}).get('collected') or 0
    overdue = _bydept(base.filter(outstanding_amount__gt=0, due_date__lt=today),
                      od_amt=Sum('outstanding_amount'), od_est=Sum('estimated_amount'), od_cnt=Count('id'))
    current = _bydept(base.filter(outstanding_amount__gt=0, due_date__gte=month_start, due_date__lte=month_end),
                      cur_est=Sum('estimated_amount'), cur_cnt=Count('id'))

    rows = []
    for d in dept_list:
        o = overall.get(d, {})
        od = overdue.get(d, {})
        cu = current.get(d, {})
        est = float(o.get('estimated') or 0)
        collected = float(o.get('collected') or 0)
        od_est = float(od.get('od_est') or 0)
        cur_est = float(cu.get('cur_est') or 0)
        rate = round(min(collected / est * 100, 999.99), 1) if est > 0 else None
        rows.append({
            'dept': d,
            'estimated': round(est, 2),
            'invoiced': round(float(o.get('invoiced') or 0), 2),
            'outstanding': round(float(o.get('outstanding') or 0), 2),
            'collected': round(collected, 2),
            'overdue_amount': round(float(od.get('od_amt') or 0), 2),
            'overdue_count': int(od.get('od_cnt') or 0),
            'record_count': int(o.get('cnt') or 0),
            'rate': rate,
            'current_due_est': round(cur_est, 2),
            'overdue_est': round(od_est, 2),
            'month_target': round(cur_est + od_est, 2),   # 本月到期目标 = 当期 + 逾期 上账
        })
    rows.sort(key=lambda r: r['outstanding'], reverse=True)

    totals = {
        'estimated': round(sum(r['estimated'] for r in rows), 2),
        'invoiced': round(sum(r['invoiced'] for r in rows), 2),
        'outstanding': round(sum(r['outstanding'] for r in rows), 2),
        'collected': round(sum(r['collected'] for r in rows), 2),
        'overdue_amount': round(sum(r['overdue_amount'] for r in rows), 2),
        'overdue_count': sum(r['overdue_count'] for r in rows),
        'month_target': round(sum(r['month_target'] for r in rows), 2),
    }
    totals['rate'] = round(min(totals['collected'] / totals['estimated'] * 100, 999.99), 1) if totals['estimated'] > 0 else None
    return ok({'ref_month': f'{today.year}年{today.month}月', 'rows': rows, 'totals': totals})


# ══════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# P4 目标分解 — 年度目标自上而下分解到事业部 + 月度进度
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def analytics_target_decomp(request):
    """年度目标 → 各事业部分解 → 各月目标/实际/完成率。"""
    year = _int_param(request, 'year', datetime.date.today().year)

    from caiwu.models import FinancialTarget, FinancialEntry, ImportBatch, L1Category
    from django.db.models import Sum as _Sum

    def _scope_bu(qs, field='business_unit'):
        if request.pk_role == 'super_admin':
            return qs
        # 无授权部门 → 空集（不再短路跳过过滤，杜绝越权看全部事业部目标）
        return qs.filter(**{field + '__in': request.pk_depts or []})

    # Annual targets (month=0)
    annual_qs = _scope_bu(FinancialTarget.objects.filter(year=year, month=0))
    annual_by_bu = {t.business_unit: t for t in annual_qs}

    # Monthly targets (month 1-12)
    monthly_qs = _scope_bu(FinancialTarget.objects.filter(year=year, month__gt=0))
    monthly_by_bu = {}
    for t in monthly_qs:
        monthly_by_bu.setdefault(t.business_unit, {})[t.month] = t

    # Actuals from published 部门明细表 (FinancialEntry), aggregated by BU+month for 主营业务收入
    rev_l1_ids = list(L1Category.objects.filter(name='主营业务收入').values_list('id', flat=True))
    agg_qs = _scope_bu(FinancialEntry.objects.filter(
        batch__status=ImportBatch.STATUS_PUBLISHED,
        batch__batch_type=ImportBatch.TYPE_DEPT,
        batch__year=year,
        l1_id__in=rev_l1_ids,
    ), field='batch__business_unit').values('batch__business_unit', 'batch__month').annotate(amount=_Sum('amount'))
    actuals = {}
    for r in agg_qs:
        actuals.setdefault(r['batch__business_unit'], {})[r['batch__month']] = float(r['amount'] or 0)

    today = datetime.date.today()
    elapsed = today.month if today.year == year else (12 if today.year > year else 0)

    all_bus = sorted(set(annual_by_bu) | set(monthly_by_bu) | set(actuals))

    rows = []
    for bu in all_bus:
        annual_t = annual_by_bu.get(bu)
        annual_rev = float(annual_t.target_revenue) if annual_t else 0
        annual_profit = float(annual_t.target_profit) if annual_t else 0
        annual_gross = float(annual_t.target_gross_profit) if annual_t else 0

        bu_actuals = actuals.get(bu, {})
        ytd_rev = sum(bu_actuals.get(m, 0) for m in range(1, elapsed + 1))
        projected = round(ytd_rev / elapsed * 12, 2) if elapsed else None

        months = []
        for m in range(1, 13):
            mt = monthly_by_bu.get(bu, {}).get(m)
            actual = bu_actuals.get(m, 0)
            t_rev = float(mt.target_revenue) if mt else None
            achieved = round(actual / t_rev * 100, 1) if t_rev else None
            months.append({
                'month': m,
                'target_revenue': t_rev,
                'actual_revenue': actual,
                'achieved': achieved,
                'is_past': m <= elapsed,
            })

        rows.append({
            'bu': bu,
            'annual_target_revenue': annual_rev,
            'annual_target_profit': annual_profit,
            'annual_target_gross': annual_gross,
            'ytd_actual_revenue': ytd_rev,
            'ytd_achieved': round(ytd_rev / annual_rev * 100, 1) if annual_rev else None,
            'projected': projected,
            'gap': round(annual_rev - projected, 2) if projected is not None and annual_rev else None,
            'months': months,
        })

    # Group-level summary
    total_annual = sum(r['annual_target_revenue'] for r in rows)
    total_ytd = sum(r['ytd_actual_revenue'] for r in rows)
    total_projected = round(total_ytd / elapsed * 12, 2) if elapsed and total_ytd else None

    return ok({
        'year': year,
        'elapsed': elapsed,
        'rows': rows,
        'summary': {
            'total_annual_target': total_annual,
            'total_ytd_actual': total_ytd,
            'total_ytd_achieved': round(total_ytd / total_annual * 100, 1) if total_annual else None,
            'total_projected': total_projected,
            'total_gap': round(total_annual - total_projected, 2) if total_projected is not None else None,
        },
    })





# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
