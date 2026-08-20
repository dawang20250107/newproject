"""预收预付（advances）业务域视图：单表 + direction（预收/预付）判别，挂项目台账。
列表/KPI/汇总/可用额/可冲销记录、导入导出、分期、核销与批量核销、差额汇总、
冲销工作台等。共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403
from paikuan.list_filters import build_filter_q, resolve_sort

# 预收预付 (Advance receipts / prepayments) — 单表 + direction 判别，挂项目台账
# ══════════════════════════════════════════════════════════════════════════════

# Excel 风格列头筛选 + 排序白名单：仅登记真实 DB 列（计算列/派生状态不在此）。
# project__short_name 走关联 lookup，命中时需 .distinct()（multi=True）。
ADVANCE_FILTER_REGISTRY = {
    'direction':              {'type': 'enum',   'col': 'direction'},
    'counterparty':           {'type': 'text',   'col': 'counterparty'},
    'delivery_dept':          {'type': 'enum',   'col': 'delivery_dept'},
    'occur_date':             {'type': 'date',   'col': 'occur_date'},
    'expected_writeoff_date': {'type': 'date',   'col': 'expected_writeoff_date'},
    'advance_amount':         {'type': 'number', 'col': 'advance_amount'},
    'written_off_amount':     {'type': 'number', 'col': 'written_off_amount'},
    'balance_amount':         {'type': 'number', 'col': 'balance_amount'},
    'project_short_name':     {'type': 'text',   'col': 'project__short_name', 'multi': True},
}

def _advance_dept_filter(qs, request):
    """Dept-scope advances. Project-linked rows use project.is_shared for the
    shared-only rule; standalone rows are matched on delivery_dept only."""
    return _ar_dept_filter(qs, request, shared_field='project__is_shared')


def _advance_date_range(request):
    """解析实际收付区间参数 → (start_date|None, end_date|None)。"""
    sd = ed = None
    s_raw = _normalize_date(request.GET.get('start_date'))
    e_raw = _normalize_date(request.GET.get('end_date'))
    if s_raw:
        sd = datetime.date.fromisoformat(str(s_raw)[:10])
    if e_raw:
        ed = datetime.date.fromisoformat(str(e_raw)[:10])
    return sd, ed


def _apply_advance_filters(qs, request):
    """Shared dimension filters for advance list + kpi + summary."""
    direction = request.GET.get('direction', '').strip()
    if direction in ADVANCE_DIRECTIONS:
        qs = qs.filter(direction=direction)
    project_id = request.GET.get('project_id', '').strip()
    if project_id:
        qs = qs.filter(project_id=int(project_id))
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    year = request.GET.get('year', '').strip()
    if year:
        qs = qs.filter(occur_year=int(year))
    month = request.GET.get('month', '').strip()
    if month:
        qs = qs.filter(occur_month=int(month))
    # 实际收付时间区间：按「分期收付日期」筛（真实现金事件日）——主表
    # occur_year/month 是合作发生年月（业务归属维度，由上方 year/month 参数承担），
    # 一条记录可分多期收付，区间命中任意一期即入选。历史数据已由迁移 0032 回填
    # 分期，凡有金额必有分期。用 id 子查询而非反向 JOIN，避免多期记录在下游
    # Sum/count 里被重复计。
    sd, ed = _advance_date_range(request)
    if sd or ed:
        inst = AdvanceInstallment.objects.all()
        if sd:
            inst = inst.filter(occur_date__gte=sd)
        if ed:
            inst = inst.filter(occur_date__lte=ed)
        qs = qs.filter(id__in=inst.values('advance_record_id'))
    counterparty = request.GET.get('counterparty', '').strip()
    if counterparty:
        qs = qs.filter(counterparty__icontains=counterparty)
    status = request.GET.get('writeoff_status', '').strip()
    if status == '未核销':
        qs = qs.filter(balance_amount__gt=0, written_off_amount__lte=0)
    elif status == '部分核销':
        qs = qs.filter(balance_amount__gt=0, written_off_amount__gt=0)
    elif status == '已核销':
        qs = qs.filter(balance_amount__lte=0)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(counterparty__icontains=q) |
                       Q(project__short_name__icontains=q) |
                       Q(project__project_no__icontains=q) |
                       Q(notes__icontains=q))
    # Excel 风格列头筛选（白名单驱动，叠加在既有维度筛选之上）
    fq, fq_distinct = build_filter_q(request.GET.get('filters', ''), ADVANCE_FILTER_REGISTRY)
    if fq:
        qs = qs.filter(fq)
        if fq_distinct:
            qs = qs.distinct()
    return qs


@csrf_exempt
@pk_required()
def advances(request):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied

    if request.method == 'GET':
        today = timezone.localdate()
        qs = _advance_dept_filter(
            AdvanceRecord.objects.select_related('project', 'created_by'), request)
        qs = _apply_advance_filters(qs, request)
        # 区间联动（现金口径）：选了收付时间时，行内 预收/预付金额=区间内分期收付合计、
        # 已核销=区间内核销合计（按核销日期），与 KPI/合计同口径——记录整笔金额不再出现。
        sd, ed = _advance_date_range(request)
        _range_on = bool(sd or ed)
        if _range_on:
            inst_sq = AdvanceInstallment.objects.filter(advance_record=OuterRef('pk'))
            wo_sq = AdvanceWriteoff.objects.filter(advance_record=OuterRef('pk'))
            if sd:
                inst_sq = inst_sq.filter(occur_date__gte=sd)
                wo_sq = wo_sq.filter(writeoff_date__gte=sd)
            if ed:
                inst_sq = inst_sq.filter(occur_date__lte=ed)
                wo_sq = wo_sq.filter(writeoff_date__lte=ed)
            _dec0 = Value(Decimal('0'), output_field=DecimalField(max_digits=15, decimal_places=2))
            qs = qs.annotate(
                range_amount=Coalesce(Subquery(
                    inst_sq.values('advance_record').annotate(s=Sum('amount')).values('s')), _dec0),
                range_written_off=Coalesce(Subquery(
                    wo_sq.values('advance_record').annotate(s=Sum('amount')).values('s')), _dec0),
            )
        # 列头排序仅作用于分页列表（汇总不受影响）；非法/未指定回退模型默认排序。
        # 区间联动时金额/核销列显示的是区间值，排序须同口径重映射到注解列，避免「排序按
        # 整笔、显示按区间」的错位。
        sort_by = resolve_sort(request.GET.get('sort'), request.GET.get('order'),
                               ADVANCE_FILTER_REGISTRY)
        if sort_by:
            if _range_on:
                _remap = {'advance_amount': 'range_amount',
                          'written_off_amount': 'range_written_off'}
                _sign = '-' if sort_by.startswith('-') else ''
                _bare = sort_by.lstrip('-')
                sort_by = _sign + _remap.get(_bare, _bare)
            qs = qs.order_by(sort_by)
        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))

        qs_agg = _apply_advance_filters(
            _advance_dept_filter(AdvanceRecord.objects.all(), request), request)
        ids = list(qs_agg.order_by().values_list('id', flat=True))
        total = len(ids)
        base = AdvanceRecord.objects.filter(id__in=ids)

        def _range_sums(d_qs):
            """区间内 (分期收付合计, 核销合计)。"""
            inst = AdvanceInstallment.objects.filter(advance_record__in=d_qs)
            wo = AdvanceWriteoff.objects.filter(advance_record__in=d_qs)
            if sd:
                inst = inst.filter(occur_date__gte=sd)
                wo = wo.filter(writeoff_date__gte=sd)
            if ed:
                inst = inst.filter(occur_date__lte=ed)
                wo = wo.filter(writeoff_date__lte=ed)
            return (inst.aggregate(s=Sum('amount'))['s'] or 0,
                    wo.aggregate(s=Sum('amount'))['s'] or 0)

        def _dir_summary(direction):
            d_qs = base.filter(direction=direction)
            agg = d_qs.aggregate(
                amt=Sum('advance_amount'),
                wo=Sum('written_off_amount'),
                rf=Sum('refunded_amount'),
                bal=Sum('balance_amount', filter=Q(balance_amount__gt=0)),
            )
            amt, wo_amt = agg['amt'] or 0, agg['wo'] or 0
            if _range_on:
                amt, wo_amt = _range_sums(d_qs)   # 合计与行内同口径：区间现金
            overdue = (d_qs.filter(balance_amount__gt=0,
                                   expected_writeoff_date__lt=today)
                       .aggregate(s=Sum('balance_amount'))['s'] or 0)
            return {
                'count': d_qs.count(),
                'advance_amount': str(amt),
                'written_off': str(wo_amt),
                'refunded': str(agg['rf'] or 0),
                'balance': str(agg['bal'] or 0),
                'overdue_balance': str(overdue),
            }

        summary = {
            'count': total,
            'cash_basis': _range_on,
            '预收': _dir_summary('预收'),
            '预付': _dir_summary('预付'),
        }

        perms = get_request_perms(request)
        include_wo = request.GET.get('include_writeoffs', '') in ('1', 'true')
        items = list(qs[(page - 1) * size: page * size])
        rows = []
        for r in items:
            d = r.to_dict(today=today, include_writeoffs=include_wo)
            if _range_on:
                d['advance_amount'] = str(r.range_amount)
                d['written_off_amount'] = str(r.range_written_off)
            rows.append(apply_ar_view_mask(d, perms, 'advance'))
        return ok({'items': rows, 'total': total, 'page': page, 'size': size,
                   'summary': summary, 'cash_basis': _range_on})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _ar_visible_payload(
            request, _parse_body(request), 'advance',
            extra=('project_id', 'direction', 'occur_year', 'occur_month',
                   'occur_date', 'expected_writeoff_date', 'delivery_dept'))
        return _advance_create(request, data)

    return err('Method not allowed', 405)


def _advance_create(request, data):
    direction = (data.get('direction') or '').strip()
    if direction not in ADVANCE_DIRECTIONS:
        return err('方向无效，应为 预收 或 预付')
    year = int(data.get('occur_year', 0) or 0)
    month = int(data.get('occur_month', 0) or 0)
    if not (year and 1 <= month <= 12):
        return err('发生年月无效')

    proj = None
    project_id = data.get('project_id')
    dept = (data.get('delivery_dept') or '').strip()
    if project_id:
        try:
            proj = ARProject.objects.get(pk=int(project_id))
        except ARProject.DoesNotExist:
            return err('项目不存在', 404)
        dept = proj.delivery_dept
    if not dept:
        return err('请选择项目或填写交付部门')
    denied = _dept_denied(request, dept, '无权操作此部门')
    if denied:
        return denied

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    try:
        rec = AdvanceRecord(
            project=proj,
            delivery_dept=dept,
            direction=direction,
            counterparty=(data.get('counterparty') or '').strip(),
            occur_year=year,
            occur_month=month,
            occur_date=_normalize_date(data.get('occur_date')) or None,
            advance_amount=_dec(data.get('advance_amount', 0)),
            expected_writeoff_date=_normalize_date(data.get('expected_writeoff_date')) or None,
            notes=(data.get('notes') or '').strip(),
            created_by=user,
        )
        rec.save()
        # 总额为派生列（=收付明细之和）：创建时生成首笔收付明细，后续可多次追加
        if rec.advance_amount:
            init_date = rec.occur_date or datetime.date(year, month, 1)
            AdvanceInstallment.objects.create(
                advance_record=rec, install_no=1, amount=rec.advance_amount,
                occur_date=init_date, notes='录入初始金额')
    except Exception as e:
        return err(str(e))
    return ok(apply_ar_view_mask(
        rec.to_dict(today=timezone.localdate(), include_writeoffs=True),
        get_request_perms(request), 'advance'))


@csrf_exempt
@pk_required()
def advance_detail(request, pk):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    try:
        rec = AdvanceRecord.objects.select_related('project', 'created_by').get(pk=pk)
    except AdvanceRecord.DoesNotExist:
        return err('记录不存在', 404)
    if request.pk_role != 'super_admin':
        if rec.delivery_dept not in request.pk_depts:
            return err('无权访问', 403)
        perms = get_request_perms(request)
        if perms and perms.get('ar_shared_only') and not (rec.project and rec.project.is_shared):
            return err('无权访问', 403)
    today = timezone.localdate()

    if request.method == 'GET':
        return ok(apply_ar_view_mask(rec.to_dict(today=today, include_writeoffs=True),
                                     get_request_perms(request), 'advance'))

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _ar_visible_payload(request, _parse_body(request), 'advance',
                                   extra=('direction', 'occur_year', 'occur_month',
                                          'occur_date', 'expected_writeoff_date'))
        if 'direction' in data and data['direction'] in ADVANCE_DIRECTIONS \
                and data['direction'] != rec.direction:
            # 方向决定核销语义（预收核销挂应收回款 / 预付核销挂排款）与资金池口径，
            # 已有核销时翻转会让两侧台账互相矛盾
            if rec.writeoffs.exists():
                return err('该记录已有核销，不能修改预收/预付方向；请先删除其全部核销记录')
            # 退款只属于预付语义：已有「预付退款」回冲的记录翻成预收会让
            # refunded_amount 挂在预收上、余额仍被退款冲减，台账语义错乱
            if rec.refunds.exists():
                return err('该记录已有预付退款关联（日常收款），不能修改方向；'
                           '请先在日常收款解除关联或删除对应退款')
            rec.direction = data['direction']
        if 'counterparty' in data:
            rec.counterparty = (data['counterparty'] or '').strip()
        if 'occur_year' in data and data['occur_year']:
            rec.occur_year = int(data['occur_year'])
        if 'occur_month' in data and data['occur_month']:
            rec.occur_month = int(data['occur_month'])
        if 'occur_date' in data:
            rec.occur_date = _normalize_date(data['occur_date']) or None
        if 'advance_amount' in data:
            # 兼容旧调用方按「总额」编辑：与现总额的差值生成一笔收付明细
            # （明细为正源、总额为派生，与应收差额调整同款策略）。
            # 减额低于已核销时信号抛 ValidationError → 400（余额不能为负）
            new_total = _dec(data['advance_amount'])
            delta = new_total - (rec.advance_amount or Decimal('0'))
            if delta:
                last_inst = rec.installments.order_by('-install_no').first()
                try:
                    with transaction.atomic():
                        AdvanceInstallment.objects.create(
                            advance_record=rec,
                            install_no=(last_inst.install_no + 1) if last_inst else 1,
                            amount=delta, occur_date=rec.occur_date or timezone.localdate(),
                            notes='人工调整（按总额修改）')
                except ValidationError as e:
                    return err(str(e.message if hasattr(e, 'message') else e), 400)
                rec.advance_amount = new_total
        if 'expected_writeoff_date' in data:
            rec.expected_writeoff_date = _normalize_date(data['expected_writeoff_date']) or None
        if 'notes' in data:
            rec.notes = (data['notes'] or '').strip()
        try:
            rec.save()
        except Exception as e:
            return err(str(e))
        return ok(apply_ar_view_mask(rec.to_dict(today=today, include_writeoffs=True),
                                     get_request_perms(request), 'advance'))

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        # 删除守卫（与排款侧「有核销不能删」同纪律）：
        # · 有核销：级联删核销会连锁改写排款冲抵/应收回款，静默解开已入账的核销；
        # · 有退款：DailyReceipt.advance_record 为 SET_NULL，删除后退款现金流入仍计入
        #   资金池，而本记录的预付流出随删除消失 → 池余额单边虚增，退款成无主记录。
        if rec.writeoffs.exists():
            return err('该记录已有核销，不能删除；请先删除其全部核销记录', 409, 409)
        if rec.refunds.exists():
            return err('该记录已有预付退款关联（日常收款），不能删除；'
                       '请先在日常收款解除关联或删除对应退款', 409, 409)
        rec.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def advances_bulk_delete(request):
    """POST {ids:[...]} → 批量删除预收预付（部门作用域内）。
    与单删同一道资金安全线：有核销或退款关联的记录跳过并回传原因。"""
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    denied = _delete_denied(request)
    if denied:
        return denied
    ids = _parse_body(request).get('ids') or []
    if not isinstance(ids, list) or not ids:
        return err('请选择要删除的记录')
    try:
        ids = [int(i) for i in ids]
    except (ValueError, TypeError):
        return err('ids 必须为整数列表')
    if len(ids) > 1000:
        return err('单次删除上限 1000 条，请缩小选择范围')
    qs = _advance_dept_filter(AdvanceRecord.objects.filter(pk__in=ids), request)
    deleted, skipped = 0, []
    for rec in list(qs):
        if rec.writeoffs.exists():
            skipped.append({'id': rec.id,
                            'reason': '已有核销，不能删除；请先删除其全部核销记录'})
            continue
        if rec.refunds.exists():
            skipped.append({'id': rec.id,
                            'reason': '已有预付退款关联（日常收款），不能删除；'
                                      '请先在日常收款解除关联或删除对应退款'})
            continue
        rec.delete()
        deleted += 1
    return ok({'deleted': deleted, 'skipped': skipped,
               'message': f'已删除 {deleted} 条' + (f'；跳过 {len(skipped)} 条' if skipped else '')})


@csrf_exempt
@pk_required()
def advances_kpi(request):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    today = timezone.localdate()
    qs = _apply_advance_filters(
        _advance_dept_filter(AdvanceRecord.objects.all(), request), request)

    sd, ed = _advance_date_range(request)

    def _block(direction):
        d_qs = qs.filter(direction=direction)
        agg = d_qs.aggregate(amt=Sum('advance_amount'), wo=Sum('written_off_amount'),
                             rf=Sum('refunded_amount'),
                             bal=Sum('balance_amount', filter=Q(balance_amount__gt=0)))
        total_amt = float(agg['amt'] or 0)
        # 金额卡=区间内「实际收付」合计（分期口径）、已核销=区间内核销合计（按核销
        # 日期）——与列表行/筛选合计同口径；无区间时等于记录级存量。核销率/退款/余额
        # 保持存量口径（进度与挂账是全周期概念）。
        cash_amt = total_amt
        wo_stock = float(agg['wo'] or 0)   # 核销率恒用存量口径（全周期进度）
        wo = wo_stock
        if sd or ed:
            inst = AdvanceInstallment.objects.filter(advance_record__in=d_qs)
            wo_qs = AdvanceWriteoff.objects.filter(advance_record__in=d_qs)
            if sd:
                inst = inst.filter(occur_date__gte=sd)
                wo_qs = wo_qs.filter(writeoff_date__gte=sd)
            if ed:
                inst = inst.filter(occur_date__lte=ed)
                wo_qs = wo_qs.filter(writeoff_date__lte=ed)
            cash_amt = float(inst.aggregate(s=Sum('amount'))['s'] or 0)
            wo = float(wo_qs.aggregate(s=Sum('amount'))['s'] or 0)
        rf = float(agg['rf'] or 0)
        bal = float(agg['bal'] or 0)
        pending = d_qs.filter(balance_amount__gt=0).count()
        overdue_qs = d_qs.filter(balance_amount__gt=0, expected_writeoff_date__lt=today)
        overdue_amt = float(overdue_qs.aggregate(s=Sum('balance_amount'))['s'] or 0)
        return {
            'count': d_qs.count(),
            'advance_amount': cash_amt,
            'written_off': wo,
            'refunded': rf,
            'balance': bal,
            # 核销进度按「已核销+已退款」占比:退款也消耗预付余额,只算核销会让进度虚低。
            # 恒用存量口径（wo_stock）——区间联动只改显示金额，不改全周期进度。
            'writeoff_rate': round((wo_stock + rf) / total_amt * 100, 1) if total_amt else 100.0,
            'pending_count': pending,
            'overdue_count': overdue_qs.count(),
            'overdue_balance': overdue_amt,
        }

    return ok({'预收': _block('预收'), '预付': _block('预付')})


@csrf_exempt
@pk_required()
def advances_summary(request):
    """Group-by pivot over advances. group_by ∈ {dept, direction, counterparty, month}."""
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    qs = _apply_advance_filters(
        _advance_dept_filter(AdvanceRecord.objects.all(), request), request)
    group_by = request.GET.get('group_by', 'dept').strip()
    field_map = {
        'dept': 'delivery_dept',
        'direction': 'direction',
        'counterparty': 'counterparty',
    }
    rows = []
    if group_by == 'month':
        # 按月=实际收付口径：金额按「分期收付日期」归月（真实现金事件），不按主表
        # 入驻年月（occur_year/month 是业务归属维度，不参与金额统计）。
        # 核销/余额是记录级存量、无法无重复地摊到收付月，故月透视只给 金额+笔数。
        inst = AdvanceInstallment.objects.filter(advance_record__in=qs)
        sd, ed = _advance_date_range(request)
        if sd:
            inst = inst.filter(occur_date__gte=sd)
        if ed:
            inst = inst.filter(occur_date__lte=ed)
        agg = (inst.annotate(_m=TruncMonth('occur_date')).values('_m')
               .annotate(advance_amount=Sum('amount'),
                         count=Count('advance_record_id', distinct=True))
               .order_by('_m'))
        for r in agg:
            if not r['_m']:
                continue
            rows.append({
                'key': r['_m'].strftime('%Y-%m'),
                'year': r['_m'].year, 'month': r['_m'].month,
                'count': r['count'],
                'advance_amount': str(r['advance_amount'] or 0),
            })
    else:
        field = field_map.get(group_by, 'delivery_dept')
        agg = (qs.values(field)
               .annotate(count=Count('id'), advance_amount=Sum('advance_amount'),
                         written_off=Sum('written_off_amount'),
                         balance=Sum('balance_amount'))
               .order_by('-advance_amount'))
        for r in agg:
            rows.append({
                'key': r[field] or '(未填)',
                'count': r['count'],
                'advance_amount': str(r['advance_amount'] or 0),
                'written_off': str(r['written_off'] or 0),
                'balance': str(r['balance'] or 0),
            })
    return ok({'group_by': group_by, 'rows': rows})


@csrf_exempt
@pk_required()
def advances_by_counterparty(request):
    """GET /advances/by-counterparty — 按往来单位（预收=客户 / 预付=供应商）聚合，
    每个单位下再按项目拆分（未挂项目的散单归入「（未挂项目）」）。

    口径：
    - 金额（advance_amount）：选了实际收付区间(start_date/end_date)时 = 区间内分期
      收付合计（真实现金口径，与 KPI 金额卡一致）；未选区间 = 记录全额合计。
    - 已核销/已退款/未核销余额/逾期余额：记录级存量口径（全周期），不随区间切割。
    沿用列表同一套筛选（方向/部门/核销状态/搜索/列头筛选），部门权限隔离一致。
    """
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    today = timezone.localdate()
    qs = _apply_advance_filters(
        _advance_dept_filter(AdvanceRecord.objects.all(), request), request)
    sd, ed = _advance_date_range(request)

    def _stock(vals_qs, keys):
        return (vals_qs.values(*keys)
                .annotate(count=Count('id'),
                          advance_amount=Sum('advance_amount'),
                          written_off=Sum('written_off_amount'),
                          refunded=Sum('refunded_amount'),
                          balance=Sum('balance_amount', filter=Q(balance_amount__gt=0)),
                          overdue_balance=Sum('balance_amount', filter=Q(
                              balance_amount__gt=0, expected_writeoff_date__lt=today))))

    def _range_map(model, date_field, keys):
        """区间内合计 → {key元组: Decimal}；未选区间返回 None（用存量/全额）。
        model=AdvanceInstallment(分期收付) 或 AdvanceWriteoff(核销，按核销日期)。"""
        if not (sd or ed):
            return None
        sub = model.objects.filter(advance_record__in=qs)
        if sd:
            sub = sub.filter(**{f'{date_field}__gte': sd})
        if ed:
            sub = sub.filter(**{f'{date_field}__lte': ed})
        prefixed = [f'advance_record__{k}' for k in keys]
        return {tuple(r[p] for p in prefixed): r['s']
                for r in sub.values(*prefixed).annotate(s=Sum('amount'))}

    def _cash_map(keys):
        return _range_map(AdvanceInstallment, 'occur_date', keys)

    def _wo_map(keys):
        return _range_map(AdvanceWriteoff, 'writeoff_date', keys)

    def _row(r, cash, wo, key, extra=None):
        amt = r['advance_amount'] or 0
        wo_amt = r['written_off'] or 0
        if cash is not None:
            amt = cash.get(key) or 0
        if wo is not None:
            wo_amt = wo.get(key) or 0
        out = {
            'count': r['count'],
            'advance_amount': str(amt),
            'written_off': str(wo_amt),
            'refunded': str(r['refunded'] or 0),
            'balance': str(r['balance'] or 0),
            'overdue_balance': str(r['overdue_balance'] or 0),
        }
        if extra:
            out.update(extra)
        return out

    # 单位级
    cp_cash = _cash_map(['counterparty'])
    cp_wo = _wo_map(['counterparty'])
    cp_rows = {}
    for r in _stock(qs, ['counterparty']):
        cp = r['counterparty'] or '（未填单位）'
        cp_rows[cp] = _row(r, cp_cash, cp_wo, (r['counterparty'],),
                           {'counterparty': cp, 'projects': [], 'project_count': 0})
    # 项目级（挂在单位下；散单=（未挂项目））
    pj_cash = _cash_map(['counterparty', 'project_id'])
    pj_wo = _wo_map(['counterparty', 'project_id'])
    for r in (_stock(qs, ['counterparty', 'project_id', 'project__short_name'])):
        cp = r['counterparty'] or '（未填单位）'
        parent = cp_rows.get(cp)
        if parent is None:
            continue
        parent['projects'].append(_row(
            r, pj_cash, pj_wo, (r['counterparty'], r['project_id']),
            {'project_id': r['project_id'],
             'short_name': r['project__short_name'] or '（未挂项目）'}))
    for row in cp_rows.values():
        row['projects'].sort(key=lambda x: -float(x['balance'] or 0))
        row['project_count'] = sum(1 for p in row['projects'] if p['project_id'])
    rows = sorted(cp_rows.values(),
                  key=lambda x: (-float(x['balance'] or 0), -float(x['advance_amount'] or 0)))
    return ok({'rows': rows, 'cash_basis': bool(sd or ed)})


@csrf_exempt
@pk_required()
def advances_available(request):
    """可用预收/预付查询 — 供应收回款 / 排款界面联动弹出。

    返回指定方向(默认预收)下仍有未核销余额(balance_amount > 0)的明细及合计。

    匹配口径（可组合，按 OR 取并集）：
    - project_id：挂在该项目下的预收/预付；
    - customer：未挂项目、且往来单位 = 该客户名（忽略大小写/首尾空格的精确匹配）
      的「散单」预收/预付，用于"未挂项目、只记了客户名"的预收也能在回款界面弹出。
      采用精确匹配以保证与「应收明细→可冲抵预收」双向一致、口径严谨。
    另有 dept / counterparty 作为附加的 AND 过滤（部门精确、往来单位包含）。
    只读，不改动任何账务。
    """
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    denied = _ar_field_denied(request, 'adv_amount')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    direction = (request.GET.get('direction', '预收').strip() or '预收')
    if direction not in ADVANCE_DIRECTIONS:
        return err('方向无效，应为 预收 或 预付')
    today = timezone.localdate()
    qs = _advance_dept_filter(
        AdvanceRecord.objects.select_related('project'), request)
    qs = qs.filter(direction=direction, balance_amount__gt=0)

    # 并集匹配：本项目 ∪ 散单(无项目)且客户名匹配
    match_clauses = []
    project_id = request.GET.get('project_id', '').strip()
    if project_id:
        match_clauses.append(Q(project_id=int(project_id)))
    customer = request.GET.get('customer', '').strip()
    if customer:
        match_clauses.append(Q(project__isnull=True, counterparty__iexact=customer))
    if match_clauses:
        combined = match_clauses[0]
        for c in match_clauses[1:]:
            combined |= c
        qs = qs.filter(combined)

    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    counterparty = request.GET.get('counterparty', '').strip()
    if counterparty:
        qs = qs.filter(counterparty__icontains=counterparty)
    agg = qs.aggregate(total=Sum('balance_amount'), cnt=Count('id'))
    total_balance = (agg['total'] or Decimal('0')).quantize(Decimal('0.01'))
    items = [{
        'id': r.id,
        'project_id': r.project_id,
        'project_no': r.project.project_no if r.project_id else None,
        'short_name': r.project.short_name if r.project_id else None,
        'match_type': 'project' if r.project_id else 'customer',
        'counterparty': r.counterparty,
        'delivery_dept': r.delivery_dept,
        'occur_date': str(r.occur_date) if r.occur_date else None,
        'advance_amount': str(r.advance_amount),
        'balance_amount': str(r.balance_amount),
        'expected_writeoff_date': (str(r.expected_writeoff_date)
                                   if r.expected_writeoff_date else None),
        **r.aging_dict(today),
    } for r in qs.order_by('-balance_amount')[:50]]
    return ok({
        'direction': direction,
        'count': agg['cnt'] or 0,
        'total_balance': str(total_balance),
        'items': items,
    })


@csrf_exempt
@pk_required()
def advance_offsettable_records(request):
    """列出可被预收冲抵的应收明细（未收余额 > 0），供预收核销弹窗选择。

    入参二选一：
    - project_id：该项目下的应收明细（预收挂了项目时）；
    - customer：按项目客户名匹配的应收明细（散单预收，未挂项目时）。
    """
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    project_id = request.GET.get('project_id', '').strip()
    customer = request.GET.get('customer', '').strip()
    qs = ARRecord.objects.select_related('project').filter(outstanding_amount__gt=0)
    if project_id:
        qs = qs.filter(project_id=int(project_id))
    elif customer:
        # 与 advances_available 对称：散单预收的往来单位 == 项目合同名（即客户名，精确匹配）
        qs = qs.filter(project__customer_name__iexact=customer)
    else:
        return err('缺少 project_id 或 customer')
    if request.pk_role != 'super_admin':
        qs = qs.filter(delivery_dept__in=request.pk_depts)
    qs = qs.order_by('project__short_name', 'operation_year', 'operation_month')
    by_customer = bool(customer) and not project_id
    items = [{
        'id': r.id,
        'project_id': r.project_id,
        'short_name': r.project.short_name,
        'operation_year': r.operation_year,
        'operation_month': r.operation_month,
        'estimated_amount': str(r.estimated_amount),
        'outstanding_amount': str(r.outstanding_amount),
        'label': ((f'{r.project.short_name} · ' if by_customer else '')
                  + f'{r.operation_year}-{r.operation_month:02d} · 未收 '
                  f'{r.outstanding_amount:,.2f}'),
    } for r in qs[:100]]
    return ok({'items': items})


@csrf_exempt
@pk_required()
def advance_template(request):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '预收预付明细'
    headers = ['方向(预收/预付)*', '项目简称', '交付部门', '往来单位*', '发生年*', '发生月*',
               '款项日期', '预收/预付金额', '预计核销日期', '核销金额', '核销日期', '备注']
    _header_row(ws, headers, color='6A1B9A')
    tip_vals = [
        '★必填：预收=客户预付给我们(现金流入)，预付=我们预付供应商(现金流出)',
        '选填：填项目台账中的"项目简称"（精确匹配）；无对应项目可留空，仅填往来单位',
        '选填：未填项目简称时必填本列（交付部门）；填了项目则自动取项目部门',
        '★必填：往来单位（预收填客户、预付填供应商）',
        '★必填：4位整数，如 2026',
        '★必填：1-12 的整数',
        '选填：款项实际收/付日期（驱动现金流），格式 2026-01-15 / 2026年1月15日 均可',
        '选填：本笔预收/预付金额（元）；未核销余额 = 金额 − 累计核销',
        '选填：预计核销日期，超期未核销将预警；格式同上',
        '选填：本次核销(冲减)金额（元）；同一笔可多次核销，多次导入追加不覆盖',
        '选填：核销日期，格式同上',
        '选填备注',
    ]
    ws.append(tip_vals)
    tip_row = ws.max_row
    tip_fill = PatternFill('solid', fgColor='F3E5F5')
    tip_font = Font(italic=True, color='4A148C', size=9)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(tip_row, c)
        cell.fill = tip_fill
        cell.font = tip_font
        cell.alignment = Alignment(wrap_text=True)
    ws.row_dimensions[tip_row].height = 60
    ws.append(['预收', EXAMPLE_ROW_MARKER, '', '示例客户', 2026, 1, '2026-01-15',
               100000, '2026-06-30', 30000, '2026-03-10',
               '示例（此行含"示例"标记，导入时自动跳过）'])
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18
    return _export_response(wb, '预收预付导入模板.xlsx')


@csrf_exempt
@pk_required()
def advance_import(request):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _write_denied(request)
    if denied:
        return denied
    f = request.FILES.get('file')
    if not f:
        return err('请上传文件')
    if getattr(f, 'size', 0) > 5 * 1024 * 1024:
        return err('文件过大，请确认文件不超过5MB')
    try:
        wb = openpyxl.load_workbook(f, data_only=True)
        ws = wb.active
        # 防解压炸弹：5MB 压缩包也可能展开出海量单元格，先做总量护栏
        if (ws.max_row or 0) * (ws.max_column or 0) > 400_000:
            return err('表格过大（超过 40 万单元格），请拆分后再导入')
    except Exception as e:
        return err(f'无法读取Excel: {e}')

    headers = [str(ws.cell(1, c).value or '').strip() for c in range(1, ws.max_column + 1)]
    col_map = {h: i + 1 for i, h in enumerate(headers)}
    _ALIASES = {
        '方向(预收/预付)*': ['方向(预收/预付)*', '方向(预收/预付)', '方向'],
        '项目简称': ['项目简称', '项目简称*'],
        '交付部门': ['交付部门'],
        '往来单位*': ['往来单位*', '往来单位'],
        '发生年*': ['发生年*', '发生年'],
        '发生月*': ['发生月*', '发生月'],
        '款项日期': ['款项日期', '款项日期(YYYY-MM-DD)'],
        '预收/预付金额': ['预收/预付金额', '金额'],
        '预计核销日期': ['预计核销日期'],
        '核销金额': ['核销金额'],
        '核销日期': ['核销日期'],
        '备注': ['备注'],
    }

    def _resolve_idx(name):
        for h in _ALIASES.get(name, [name]):
            if h in col_map:
                return col_map[h]
        return None

    def _cv_raw(row, name):
        idx = _resolve_idx(name)
        return ws.cell(row, idx).value if idx else None

    def _cv(row, name):
        v = _cv_raw(row, name)
        return str(v).strip() if v is not None else ''

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    search_depts = None if request.pk_role == 'super_admin' else request.pk_depts
    errors = []
    plan = []   # 通过校验、待写入的行

    # ══ 阶段一：逐行校验（不写库）。示例/提示/空行静默忽略，问题行收集错误 ══════════
    for ri in range(2, ws.max_row + 1):
        direction = _cv(ri, '方向(预收/预付)*')
        short_name = _cv(ri, '项目简称')
        counterparty = _cv(ri, '往来单位*')
        if EXAMPLE_ROW_MARKER in short_name or direction.startswith('★'):
            continue
        if direction not in ADVANCE_DIRECTIONS:
            if not direction and not counterparty and not short_name:
                continue   # 整行空白：静默忽略
            errors.append(f'第{ri}行: 方向"{direction}"无效，应为 预收/预付')
            continue
        proj = None
        dept = _cv(ri, '交付部门')
        if short_name:
            proj = _match_project_by_short_name(short_name, allowed_depts=search_depts)
            if not proj:
                errors.append(f'第{ri}行: 项目简称"{short_name}"未匹配到项目，请核对简称或先在项目台账建项目')
                continue
            dept = proj.delivery_dept
        if not dept:
            errors.append(f'第{ri}行: 未填项目简称时必须填写交付部门')
            continue
        if request.pk_role != 'super_admin' and dept not in request.pk_depts:
            errors.append(f'第{ri}行: 无权操作部门"{dept}"')
            continue
        if not counterparty:
            errors.append(f'第{ri}行: 往来单位必填（按对手方归集，缺失将无法批量核销）')
            continue
        # Excel 数字单元格常以 "2026.0" 形态到达，裸 int() 会 ValueError 整个请求 500；
        # 与应收导入同口径：int(float(...)) + 兜底报行号错误
        try:
            year = int(float(_cv(ri, '发生年*') or 0))
            month = int(float(_cv(ri, '发生月*') or 0))
        except (ValueError, TypeError):
            errors.append(f'第{ri}行: 发生年月无效（年={_cv(ri, "发生年*") or "空"} 月={_cv(ri, "发生月*") or "空"}）')
            continue
        if not (year and 1 <= month <= 12):
            errors.append(f'第{ri}行: 发生年月无效（年={_cv(ri, "发生年*") or "空"} 月={_cv(ri, "发生月*") or "空"}），运作月需 1-12')
            continue
        wo_amount = _cv(ri, '核销金额')
        wo_date = _normalize_date(_cv_raw(ri, '核销日期'))
        if wo_amount and not wo_date:
            errors.append(f'第{ri}行: 填了「核销金额」却没填有效「核销日期」，请补填或清空核销金额')
            continue
        plan.append({'ri': ri, 'proj': proj, 'dept': dept, 'direction': direction,
                     'counterparty': counterparty, 'year': year, 'month': month,
                     'occur_date': _normalize_date(_cv_raw(ri, '款项日期')) or None,
                     'advance_amount': _dec(_cv(ri, '预收/预付金额') or 0),
                     'expected_writeoff_date': _normalize_date(_cv_raw(ri, '预计核销日期')) or None,
                     'notes': _cv(ri, '备注'), 'wo_amount': wo_amount, 'wo_date': wo_date})

    if errors:
        return ok({
            'rejected': True, 'created': 0, 'updated': 0, 'errors': errors,
            'message': (f'导入未执行：发现 {len(errors)} 处问题，已全部列出。'
                        f'请在表格中按提示修正后重新导入（整表全部通过才会写入，不会漏导）。'),
        })

    # ══ 阶段二：全部通过 → 一次性写入（整体事务，任一失败回滚）═══════════════════════
    created = 0
    try:
        skipped_dup = 0
        with transaction.atomic():
            for p in plan:
                # 业务防重键:方向+部门+往来单位+发生年月+金额+款项日期——同一文件重复导入
                # 或文件内重复行不再重复建账(金额/现金流/余额翻倍)。同键确需多笔时,
                # 请在备注或款项日期上做出区分后再导。
                if AdvanceRecord.objects.filter(
                        direction=p['direction'], delivery_dept=p['dept'],
                        counterparty=p['counterparty'], occur_year=p['year'],
                        occur_month=p['month'], advance_amount=p['advance_amount'],
                        occur_date=p['occur_date']).exists():
                    skipped_dup += 1
                    continue
                rec = AdvanceRecord(
                    project=p['proj'], delivery_dept=p['dept'], direction=p['direction'],
                    counterparty=p['counterparty'], occur_year=p['year'], occur_month=p['month'],
                    occur_date=p['occur_date'], advance_amount=p['advance_amount'],
                    expected_writeoff_date=p['expected_writeoff_date'],
                    notes=p['notes'], created_by=user,
                )
                rec.save()
                # 总额为派生列：导入金额作为首笔收付明细（须先于核销生效）
                if rec.advance_amount:
                    AdvanceInstallment.objects.create(
                        advance_record=rec, install_no=1, amount=rec.advance_amount,
                        occur_date=rec.occur_date or datetime.date(p['year'], p['month'], 1),
                        notes='导入初始金额')
                if p['wo_amount'] and p['wo_date']:
                    amt = _dec(p['wo_amount'])
                    if amt > 0 and not rec.writeoffs.filter(writeoff_date=p['wo_date'], amount=amt).exists():
                        max_no = rec.writeoffs.aggregate(m=Max('writeoff_no')).get('m') or 0
                        AdvanceWriteoff.objects.create(
                            advance_record=rec, writeoff_no=max_no + 1,
                            amount=amt, writeoff_date=p['wo_date'], notes='导入核销')
                created += 1
    except Exception as e:
        return ok({
            'rejected': True, 'created': 0, 'updated': 0,
            'errors': [f'写入阶段发生错误并已回滚：{e}。请检查数据后重试。'],
            'message': '导入未执行（写入阶段出错，已整体回滚，不会出现半截数据）。',
        })

    return ok({'created': created, 'updated': 0, 'skipped': skipped_dup,
               'errors': ([f'跳过 {skipped_dup} 行重复记录（方向+部门+往来单位+发生年月+金额+日期 已存在）']
                          if skipped_dup else [])})


_ADVANCE_AI_SYS = (
    '你是企业预收预付台账的数据质检助手。下面是一批待导入的预收预付记录（已通过基础格式校验）。'
    '请只挑出"疑似有问题"的行，找规则难以发现的软问题：往来单位像乱码/测试数据/占位符；'
    '金额明显异常（0元/极大极小/疑似少一个零）；同一往来单位方向/金额相互矛盾；疑似重复行。'
    '严格只返回 JSON 数组，每个元素形如 '
    '{"row":行号,"field":"字段名","issue":"问题简述","suggestion":"修正建议(可空)","severity":"high|medium|low"}。'
    '没有发现问题就返回 []。不要输出 JSON 以外的任何文字。'
)

_ADVANCE_COLUMNS = [
    {'key': 'direction', 'label': '方向'},
    {'key': 'short_name', 'label': '项目简称'},
    {'key': 'dept', 'label': '交付部门'},
    {'key': 'counterparty', 'label': '往来单位'},
    {'key': 'amount', 'label': '金额'},
    {'key': 'year', 'label': '发生年'},
    {'key': 'month', 'label': '发生月'},
    {'key': 'notes', 'label': '备注'},
]


@csrf_exempt
@pk_required()
def advance_import_precheck(request):
    """预收预付导入预检：规则校验 + AI 复核。只读不落库。
    用户确认后由前端重新提交文件到 /import 写库（AR 通用「文件留存+重提」模式）。"""
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    denied = _write_denied(request)
    if denied:
        return denied
    f = request.FILES.get('file')
    if not f:
        return err('请上传文件')
    if getattr(f, 'size', 0) > 5 * 1024 * 1024:
        return err('文件过大，请确认文件不超过5MB')
    try:
        wb = openpyxl.load_workbook(f, data_only=True)
        ws = wb.active
        # 防解压炸弹：5MB 压缩包也可能展开出海量单元格，先做总量护栏
        if (ws.max_row or 0) * (ws.max_column or 0) > 400_000:
            return err('表格过大（超过 40 万单元格），请拆分后再导入')
    except Exception as e:
        return err(f'无法读取Excel: {e}')

    data_rows = ws.max_row - 1
    if data_rows > PRECHECK_MAX:
        return ok({'skipPrecheck': True, 'total': data_rows,
                   'reason': f'数据量较大（约 {data_rows} 行），已跳过 AI 预检，直接导入。'})

    headers = [str(ws.cell(1, c).value or '').strip() for c in range(1, ws.max_column + 1)]
    col_map = {h: c + 1 for c, h in enumerate(headers)}
    _ALIASES = {
        '方向(预收/预付)*': ['方向(预收/预付)*', '方向(预收/预付)', '方向'],
        '项目简称': ['项目简称', '项目简称*'],
        '交付部门': ['交付部门'],
        '往来单位*': ['往来单位*', '往来单位'],
        '发生年*': ['发生年*', '发生年'],
        '发生月*': ['发生月*', '发生月'],
        '预收/预付金额': ['预收/预付金额', '金额'],
        '备注': ['备注'],
    }

    def _resolve_idx(name):
        for h in _ALIASES.get(name, [name]):
            if h in col_map:
                return col_map[h]
        return None

    def _cv(row, name):
        idx = _resolve_idx(name)
        v = ws.cell(row, idx).value if idx else None
        return str(v).strip() if v is not None else ''

    search_depts = None if request.pk_role == 'super_admin' else request.pk_depts
    report_rows, ai_input = [], []

    for ri in range(2, ws.max_row + 1):
        direction = _cv(ri, '方向(预收/预付)*')
        short_name = _cv(ri, '项目简称')
        counterparty = _cv(ri, '往来单位*')
        if EXAMPLE_ROW_MARKER in short_name or direction.startswith('★'):
            continue
        if not direction and not counterparty and not short_name:
            continue
        rule_issue = None
        if direction not in ADVANCE_DIRECTIONS:
            rule_issue = f'方向"{direction}"无效，应为 预收/预付'
        elif short_name:
            proj = _match_project_by_short_name(short_name, allowed_depts=search_depts)
            if not proj:
                rule_issue = f'项目简称"{short_name}"未匹配到项目，请核对简称或先在项目台账建项目'
        else:
            dept = _cv(ri, '交付部门')
            if not dept:
                rule_issue = '未填项目简称时必须填写交付部门'
            elif request.pk_role != 'super_admin' and dept not in request.pk_depts:
                rule_issue = f'无权操作部门"{dept}"'
        if not rule_issue:
            year_s = _cv(ri, '发生年*')
            month_s = _cv(ri, '发生月*')
            try:
                y, m = int(year_s or 0), int(month_s or 0)
                if not (y and 1 <= m <= 12):
                    raise ValueError()
            except (ValueError, TypeError):
                rule_issue = f'发生年月无效（年="{year_s or "空"}" 月="{month_s or "空"}"）'

        proj_val = _match_project_by_short_name(short_name, allowed_depts=search_depts) if short_name else None
        dept_val = proj_val.delivery_dept if proj_val else _cv(ri, '交付部门')
        data = {'direction': direction, 'short_name': short_name, 'dept': dept_val,
                'counterparty': counterparty, 'amount': _cv(ri, '预收/预付金额'),
                'year': _cv(ri, '发生年*'), 'month': _cv(ri, '发生月*'), 'notes': _cv(ri, '备注')}
        report_rows.append({'row': ri, 'data': data, 'ruleIssue': rule_issue, 'warn': None, 'ai': []})
        if not rule_issue:
            ai_input.append({'row': ri, 'direction': direction, 'counterparty': counterparty,
                             'amount': data['amount'], 'short_name': short_name, 'dept': dept_val})

    by_row = {}
    for fnd in _ar_ai_review(ai_input, _ADVANCE_AI_SYS):
        by_row.setdefault(fnd['row'], []).append(fnd)
    for rr in report_rows:
        rr['ai'] = by_row.get(rr['row'], [])

    return ok(_ar_precheck_report(report_rows, _ADVANCE_COLUMNS))


@csrf_exempt
@pk_required()
def advance_export(request):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    today = timezone.localdate()
    qs = _apply_advance_filters(
        _advance_dept_filter(AdvanceRecord.objects.select_related('project'), request), request)
    # 导出与列表口径一致：同样应用列头排序
    sort_by = resolve_sort(request.GET.get('sort'), request.GET.get('order'),
                           ADVANCE_FILTER_REGISTRY)
    if sort_by:
        qs = qs.order_by(sort_by)
    if qs.count() > 5000:
        return err('导出超过5000行，请缩小筛选范围')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '预收预付明细'
    columns = _visible_ar_export_cols(request, [
        (None, '方向', lambda rec, st: rec.direction),
        (None, '项目编号', lambda rec, st: rec.project.project_no if rec.project_id else ''),
        ('p_short_name', '项目简称', lambda rec, st: rec.project.short_name if rec.project_id else ''),
        (None, '交付部门', lambda rec, st: rec.delivery_dept),
        ('adv_counterparty', '往来单位', lambda rec, st: rec.counterparty),
        (None, '入驻年', lambda rec, st: rec.occur_year),
        (None, '入驻月', lambda rec, st: rec.occur_month),
        (None, '款项日期', lambda rec, st: str(rec.occur_date) if rec.occur_date else ''),
        ('adv_amount', '预收/预付金额', lambda rec, st: float(rec.advance_amount)),
        ('adv_amount', '收付明细',
         lambda rec, st: '；'.join(f'{i.occur_date}:{i.amount}'
                                   for i in rec.installments.all())),
        ('adv_writeoff', '已核销金额', lambda rec, st: float(rec.written_off_amount)),
        ('adv_writeoff', '未核销余额', lambda rec, st: float(rec.balance_amount)),
        ('adv_writeoff', '核销状态', lambda rec, st: rec.writeoff_status),
        ('adv_expected_date', '预计核销日期', lambda rec, st: str(rec.expected_writeoff_date) if rec.expected_writeoff_date else ''),
        ('adv_expected_date', '挂账天数', lambda rec, st: st['pending_days']),
        ('adv_expected_date', '是否逾期', lambda rec, st: '是' if st['is_overdue'] else ''),
        ('adv_notes', '备注', lambda rec, st: rec.notes),
    ])
    _header_row(ws, [h for _, h, _ in columns], color='6A1B9A')
    for rec in qs:
        st = rec.aging_dict(today)
        ws.append([getter(rec, st) for _, _, getter in columns])
    from wxcloudrun.excel_style import apply_money_format, append_total_row
    _money = ('预收/预付金额', '已核销金额', '未核销余额')
    apply_money_format(ws, money_headers=_money)
    append_total_row(ws, money_headers=_money)
    ws.freeze_panes = 'A2'
    return _export_response(wb, '预收预付明细.xlsx')


@csrf_exempt
@pk_required()
def advance_writeoffs(request, pk):
    try:
        rec = AdvanceRecord.objects.select_related('project').get(pk=pk)
    except AdvanceRecord.DoesNotExist:
        return err('记录不存在', 404)
    if request.pk_role != 'super_admin' and rec.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    # 显式授予对应核销操作权限（如出纳的 wo_prepaid）的岗位，可从付款台账直达核销，
    # 无需「预收预付」页面权限；未显式授予时维持原「页面 + 字段」闸口。
    _wo_action = 'wo_receive' if rec.direction == '预收' else 'wo_prepaid'
    if not _action_granted(request, _wo_action):
        denied = _page_denied(request, 'ar_advance') or _ar_field_denied(request, 'adv_writeoff')
        if denied:
            return denied

    if request.method == 'GET':
        return ok([w.to_dict() for w in
                   rec.writeoffs.select_related('payment').order_by('writeoff_no')])

    if request.method == 'POST':
        denied = _action_denied(request, _wo_action)
        if denied:
            return denied
        data = _parse_body(request)
        amount = _dec(data.get('amount', 0))
        if amount <= 0:
            return err('核销金额必须大于0')
        wo_date = _normalize_date(data.get('writeoff_date'))
        if not wo_date:
            return err('核销日期无效')
        ar_rec, offset_err = _resolve_offset_ar_record(
            request, rec, data.get('ar_record_id'), amount)
        if offset_err:
            return offset_err
        # 预付核销可关联排款记录（payment_id 仅限 direction='预付'）
        payment_id = data.get('payment_id')
        payment_obj = None
        if payment_id:
            if rec.direction != '预付':
                return err('仅「预付」核销可关联排款记录')
            try:
                # 已软删除（回收站）的排款不可关联核销：冲抵会打乱资金池/待付口径
                payment_obj = Payment.objects.get(pk=int(payment_id), deleted_at__isnull=True)
            except (Payment.DoesNotExist, ValueError, TypeError):
                return err('排款记录不存在', 404)
            if request.pk_role != 'super_admin' and payment_obj.department not in request.pk_depts:
                return err('无权操作该排款记录', 403)
            # 跨部门核销会让资金池错位：预付流出记在预付方部门，
            # 冲抵却从排款方部门扣——单池余额双向失真（集团合计反而看不出来）
            if payment_obj.department != rec.delivery_dept:
                return err(f'排款所属部门「{payment_obj.department}」与预付所属部门'
                           f'「{rec.delivery_dept}」不一致，不能关联核销')
            # 冲抵上限：累计冲抵 + 已付 不得超过计划金额（否则待付为负、口径失真）
            plan = (payment_obj.plan_adjustment
                    if payment_obj.plan_adjustment is not None else payment_obj.total_amount)
            paid = payment_obj.total_paid
            offset_now = payment_obj.prepaid_offset_amount or Decimal('0')
            room = (plan or Decimal('0')) - paid - offset_now
            if amount > room:
                return err(f'冲抵金额 {amount} 超过该排款剩余待付 {room}'
                           f'（计划 {plan} − 已付 {paid} − 已冲抵 {offset_now}）')
        try:
            with transaction.atomic():
                # 锁预收/预付行:与并发退款/另一笔核销串行,防两边校验双双通过后合计超额
                # (信号重算的非负校验在锁内成为可靠兜底)
                rec = AdvanceRecord.objects.select_for_update().get(pk=rec.pk)
                # 预付核销关联排款时:锁定该排款行并在锁内复检未软删——与「排款软删(也锁本行)」
                # 串行,防并发把核销落到刚被软删的排款上(资金池按 deleted_at 排除该冲抵,
                # 预付余额却被信号扣一块,口径裂开)。
                if payment_obj is not None:
                    try:
                        payment_obj = Payment.objects.select_for_update().get(
                            pk=payment_obj.pk, deleted_at__isnull=True)
                    except Payment.DoesNotExist:
                        return err('排款记录不存在或已被删除，无法关联核销', 404)
                last = rec.writeoffs.select_for_update().order_by('-writeoff_no').first()
                next_no = (last.writeoff_no + 1) if last else 1
                wo = AdvanceWriteoff.objects.create(
                    advance_record=rec, writeoff_no=next_no, amount=amount,
                    writeoff_date=wo_date, notes=(data.get('notes') or '').strip(),
                    payment=payment_obj)
                if ar_rec is not None:
                    pay = _create_offset_payment(rec, ar_rec, amount, wo_date)
                    AdvanceWriteoff.objects.filter(pk=wo.pk).update(
                        ar_record=ar_rec, ar_payment=pay)
                    wo.ar_record = ar_rec
                    wo.ar_payment = pay
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok(wo.to_dict())

    return err('Method not allowed', 405)


def _resolve_offset_ar_record(request, advance, ar_record_id, amount):
    """校验预收核销冲抵的应收明细。返回 (ARRecord|None, err_response|None)。"""
    if not ar_record_id:
        return None, None
    if advance.direction != '预收':
        return None, err('仅「预收」可冲抵应收账款（应收回款）')
    try:
        ar = ARRecord.objects.select_related('project').get(pk=int(ar_record_id))
    except (ARRecord.DoesNotExist, ValueError, TypeError):
        return None, err('所选应收明细不存在', 404)
    if request.pk_role != 'super_admin' and ar.delivery_dept not in request.pk_depts:
        return None, err('无权操作该应收明细所属部门', 403)
    if advance.project_id and ar.project_id != advance.project_id:
        return None, err('所选应收明细与预收所属项目不一致，无法冲抵')
    # 散单预收（未挂项目）：应收客户名称须与预收往来单位一致——与批量核销同一匹配纪律，
    # 否则 A 客户的预收可被错核到 B 客户的应收上
    if not advance.project_id:
        cust = ((ar.project.customer_name if ar.project_id else '') or '').strip()
        cp = (advance.counterparty or '').strip()
        if not cust or not cp or cust.lower() != cp.lower():
            return None, err(f'散单预收仅能冲抵「客户名称＝往来单位（{cp or "未填"}）」的应收明细')
    outstanding = ar.outstanding_amount or Decimal('0')
    if amount > outstanding:
        return None, err(f'冲抵金额 {amount:,.2f} 超过该应收未收余额 {outstanding:,.2f}')
    return ar, None


def _create_offset_payment(advance, ar_record, amount, pay_date):
    """为预收核销生成一笔「预收抵扣」回款，冲减应收 outstanding。"""
    last = ar_record.payments.select_for_update().order_by('-payment_no').first()
    next_no = (last.payment_no + 1) if last else 1
    note = f'预收核销冲抵 · 预收#{advance.id}'
    if advance.counterparty:
        note += f'（{advance.counterparty}）'
    return ARPayment.objects.create(
        ar_record=ar_record, payment_no=next_no, amount=amount,
        payment_date=pay_date, source='预收抵扣', notes=note)


def _adv_installments_payload(rec):
    """收付明细变更后的统一回包：明细 + 派生总额/余额（UI 一次刷新）。"""
    rec.refresh_from_db()
    return {
        'items': [i.to_dict() for i in rec.installments.order_by('install_no')],
        'advance_amount': str(rec.advance_amount or 0),
        'balance_amount': str(rec.balance_amount or 0),
    }


@csrf_exempt
@pk_required()
def advance_installments(request, pk):
    """GET/POST /advances/<pk>/installments — 预收/预付收付明细（多次到账/付出）。"""
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    try:
        rec = AdvanceRecord.objects.select_related('project').get(pk=pk)
    except AdvanceRecord.DoesNotExist:
        return err('记录不存在', 404)
    if request.pk_role != 'super_admin' and rec.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    denied = _ar_field_denied(request, 'adv_amount')
    if denied:
        return denied

    if request.method == 'GET':
        return ok(_adv_installments_payload(rec))

    if request.method == 'POST':
        denied = _action_denied(request, 'adv_installment')
        if denied:
            return denied
        data = _parse_body(request)
        amount = _dec(data.get('amount', 0))
        if not amount:
            return err('收付金额不能为0（可正可负，负数=退回）')
        occur = _normalize_date(data.get('occur_date'))
        if not occur:
            return err('收付日期无效（格式 2026-01-20）')
        try:
            with transaction.atomic():
                last = rec.installments.select_for_update().order_by('-install_no').first()
                AdvanceInstallment.objects.create(
                    advance_record=rec,
                    install_no=(last.install_no + 1) if last else 1,
                    amount=amount, occur_date=occur,
                    notes=(data.get('notes') or '').strip())
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok(_adv_installments_payload(rec))

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def advance_installment_detail(request, pk, iid):
    """DELETE /advances/<pk>/installments/<iid> — 删除一笔收付（总额随之回退；
    删除会使总额低于已核销时拒绝，须先删核销）。"""
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    if request.method != 'DELETE':
        return err('Method not allowed', 405)
    denied = _action_denied(request, 'adv_installment')
    if denied:
        return denied
    try:
        inst = AdvanceInstallment.objects.select_related('advance_record').get(
            pk=iid, advance_record_id=pk)
    except AdvanceInstallment.DoesNotExist:
        return err('收付明细不存在', 404)
    rec = inst.advance_record
    if request.pk_role != 'super_admin' and rec.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    denied = _ar_field_denied(request, 'adv_amount')
    if denied:
        return denied
    try:
        with transaction.atomic():
            inst.delete()
    except ValidationError as e:
        return err(str(e.message if hasattr(e, 'message') else e), 400)
    return ok(_adv_installments_payload(rec))


@csrf_exempt
@pk_required()
def advance_batch_writeoff(request, pk):
    """POST /advances/<pk>/batch-writeoff — 一笔预收按先进先出批量冲抵多条应收。

    解决「一个客户多个项目/多条应收，逐条核销太繁」：
    body: { record_ids: [int,...], amount(选填,默认=min(预收余额, 所选未收合计)),
            writeoff_date(必填) }
    按运作日期先进先出逐条冲抵：每条生成一笔核销 + 一笔「预收抵扣」回款
    （与单笔核销同一底层路径，可在两侧追溯）。
    匹配纪律与单笔核销一致：预收挂项目则只能冲该项目的应收；
    散单预收（未挂项目）则应收的客户名称须与往来单位一致。
    """
    denied = _page_denied(request, 'ar_advance') or _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _action_denied(request, 'wo_receive') or _ar_field_denied(request, 'adv_writeoff')
    if denied:
        return denied
    try:
        adv = AdvanceRecord.objects.select_related('project').get(pk=pk)
    except AdvanceRecord.DoesNotExist:
        return err('预收记录不存在', 404)
    if adv.direction != '预收':
        return err('仅「预收」可批量冲抵应收账款')
    if request.pk_role != 'super_admin' and adv.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)

    data = _parse_body(request)
    ids = data.get('record_ids') or []
    if not isinstance(ids, list) or not ids:
        return err('请勾选要冲抵的应收明细（record_ids）')
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return err('record_ids 必须为整数列表')
    wo_date = _normalize_date(data.get('writeoff_date'))
    if not wo_date:
        return err('核销日期无效（格式 2026-01-20）')

    # 散单预收（未挂项目）须有往来单位才能定位客户——空值会让客户匹配整段短路，
    # 任意客户的应收都能被冲（与单笔核销 _resolve_offset_ar_record 同口径拒绝）
    if not adv.project_id and not (adv.counterparty or '').strip():
        return err('该预收未关联项目且往来单位为空，无法确认归属客户；'
                   '请先补录往来单位后再批量冲抵')
    recs = list(ARRecord.objects.select_related('project')
                .filter(pk__in=ids).order_by('operation_date', 'id'))
    if len(recs) != len(set(ids)):
        return err('部分应收明细不存在')
    for r in recs:
        if request.pk_role != 'super_admin' and r.delivery_dept not in request.pk_depts:
            return err(f'无权操作应收明细 #{r.id} 所属部门', 403)
        if adv.project_id and r.project_id != adv.project_id:
            return err(f'应收「{r.project.short_name} {r.operation_date}」与预收所属项目不一致，无法冲抵')
        if not adv.project_id and adv.counterparty and (
                (r.project.customer_name or '').strip().lower()
                != adv.counterparty.strip().lower()):
            return err(f'应收「{r.project.short_name}」客户为「{r.project.customer_name}」，'
                       f'与预收往来单位「{adv.counterparty}」不一致，无法冲抵')
    open_recs = [r for r in recs if (r.outstanding_amount or Decimal('0')) > 0]
    if not open_recs:
        return err('所选应收明细均已结清，无未收余额可冲抵')

    balance = adv.balance_amount or Decimal('0')
    total_outstanding = sum(r.outstanding_amount for r in open_recs)
    default_amt = min(balance, total_outstanding)
    amount = _dec(data.get('amount', 0)) or default_amt
    if amount <= 0:
        return err('核销金额必须大于0')
    if amount > balance:
        return err(f'核销金额 {amount} 超过预收未核销余额 {balance}')
    if amount > total_outstanding:
        return err(f'核销金额 {amount} 超过所选应收未收合计 {total_outstanding}，'
                   f'请按 {total_outstanding} 以内录入')

    allocations = []
    try:
        with transaction.atomic():
            adv_locked = AdvanceRecord.objects.select_for_update().get(pk=adv.pk)
            remaining = amount
            last_wo = adv_locked.writeoffs.select_for_update().order_by('-writeoff_no').first()
            next_no = (last_wo.writeoff_no + 1) if last_wo else 1
            for r in open_recs:
                if remaining <= 0:
                    break
                alloc = min(remaining, r.outstanding_amount)
                pay = _create_offset_payment(adv_locked, r, alloc, wo_date)
                AdvanceWriteoff.objects.create(
                    advance_record=adv_locked, writeoff_no=next_no, amount=alloc,
                    writeoff_date=wo_date, ar_record=r, ar_payment=pay,
                    notes=f'批量核销（{len(open_recs)}条应收先进先出）')
                next_no += 1
                r.refresh_from_db()
                allocations.append({
                    'record_id': r.id, 'short_name': r.project.short_name,
                    'operation_date': str(r.operation_date) if r.operation_date else None,
                    'allocated': str(alloc),
                    'outstanding_after': str(r.outstanding_amount),
                })
                remaining -= alloc
    except ValidationError as e:
        return err(str(e.message if hasattr(e, 'message') else e), 400)

    adv.refresh_from_db()
    settled = sum(1 for a in allocations if Decimal(a['outstanding_after']) <= 0)
    return ok({
        'advance_id': adv.id, 'amount': str(amount), 'allocations': allocations,
        'advance_balance_after': str(adv.balance_amount),
        'message': (f'预收 {amount} 已按运作日期先进先出冲抵 {len(allocations)} 条应收'
                    f'（{settled} 条就此结清），预收剩余 {adv.balance_amount}'),
    })


@csrf_exempt
@pk_required()
def advance_diff_summary(request):
    """GET /advances/diff-summary — 收付差异：预收 vs 预付经「项目简称」对齐。

    每个挂了项目的预收/预付按项目聚合：预收金额、预付金额、差异（预收−预付）、
    备注（成员备注去重并列），并附两侧逐笔明细（日期/金额/往来单位）供展开。
    入参：dept(可选) q(项目名模糊,可选)。
    """
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    denied = _ar_field_denied(request, 'adv_amount')   # 金额分析端点须有金额查看权
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    dept = (request.GET.get('dept') or '').strip()
    q = (request.GET.get('q') or '').strip().lower()

    # 含散单（未挂项目）：归入「（未挂项目）」组，使合计与资金池/现金流（含全部
    # 预收预付）对平——原 project__isnull=False 排除散单是逐月对不上的根因。
    qs = (_advance_dept_filter(AdvanceRecord.objects.select_related('project'), request)
          .prefetch_related('installments'))
    if dept:
        qs = qs.filter(delivery_dept=dept)

    groups = {}
    for a in qs.order_by('occur_date', 'id'):
        linked = bool(a.project and (a.project.short_name or '').strip())
        name = a.project.short_name.strip() if linked else '（未挂项目）'
        # 散单不参与项目名搜索（无项目名）；搜索时仅命中挂项目记录
        if q and (not linked or q not in name.lower()):
            continue
        g = groups.setdefault(name, {
            'project': name,
            'dept': (a.project.delivery_dept if a.project else '') or a.delivery_dept or '',
            'in_total': Decimal('0'), 'out_total': Decimal('0'),
            'in_items': [], 'out_items': [], '_notes': [],
        })
        # 明细按「收付明细」逐笔列出（实际发生日期，多次到账/付出各一行）；
        # 无明细的历史直建记录回退用记录级款项日期
        insts = list(a.installments.all())
        balance_left = a.balance_amount or Decimal('0')
        if insts:
            items = [{
                'id': f'{a.id}-{i.id}',
                'occur_date': str(i.occur_date),
                'amount': str(i.amount or 0),
                'counterparty': a.counterparty or '—',
            } for i in sorted(insts, key=lambda x: (x.occur_date, x.install_no))]
        else:
            items = [{
                'id': str(a.id),
                'occur_date': (str(a.occur_date) if a.occur_date
                               else f'{a.occur_year}-{a.occur_month:02d}'),
                'amount': str(a.advance_amount or 0),
                'counterparty': a.counterparty or '—',
            }]
        # 未核销余额标在该记录的最后一笔明细上（余额属于记录而非单笔）
        items[-1]['balance'] = str(balance_left)
        for it in items:
            it.setdefault('balance', '0')
        if a.direction == '预收':
            g['in_total'] += a.advance_amount or Decimal('0')
            g['in_items'].extend(items)
        else:
            g['out_total'] += a.advance_amount or Decimal('0')
            g['out_items'].extend(items)
        note = (a.notes or '').strip()
        if note and note not in g['_notes']:
            g['_notes'].append(note)

    rows = []
    for g in groups.values():
        notes = '；'.join(g.pop('_notes'))[:300]
        rows.append({
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in g.items()},
            'diff': str(g['in_total'] - g['out_total']),
            'notes': notes,
        })
    # 差异绝对值大的排前面（最该关注的）
    rows.sort(key=lambda x: abs(Decimal(x['diff'])), reverse=True)

    t_in = sum(Decimal(x['in_total']) for x in rows)
    t_out = sum(Decimal(x['out_total']) for x in rows)
    return ok({
        'rows': rows,
        'summary': {'count': len(rows), 'in_total': str(t_in), 'out_total': str(t_out),
                    'diff': str(t_in - t_out)},
    })


# ── 收付差异 · 时间维度（月/周）分解 ──────────────────────────────────────────
def _period_of(d, grain):
    """把日期 d 落到时间桶。返回 (key, sort, label, anchor)。
    anchor 为该桶起点日期（月首 / 周一），用于连续补桶。"""
    if grain == 'week':
        iso = d.isocalendar()
        y, w = iso[0], iso[1]
        monday = d - datetime.timedelta(days=d.weekday())
        return f'{y}-W{w:02d}', y * 100 + w, f'{y}年第{w}周', monday
    return (f'{d.year}-{d.month:02d}', d.year * 100 + d.month,
            f'{d.year}年{d.month}月', datetime.date(d.year, d.month, 1))


def _fill_periods(present, grain):
    """在已出现的桶 anchor 之间连续补齐空桶，保证累计差异曲线不断档。
    present: {key: (sort, label, anchor)}。返回按时间排序的 [(key,label)] 全序列。"""
    if not present:
        return []
    anchors = sorted(v[2] for v in present.values())
    lo, hi = anchors[0], anchors[-1]
    seq = []
    if grain == 'week':
        cur = lo
        while cur <= hi:
            k, _, lbl, _ = _period_of(cur, 'week')
            seq.append((k, lbl))
            cur += datetime.timedelta(days=7)
    else:
        y, m = lo.year, lo.month
        while (y, m) <= (hi.year, hi.month):
            seq.append((f'{y}-{m:02d}', f'{y}年{m}月'))
            m += 1
            if m > 12:
                y, m = y + 1, 1
    return seq


def _compute_diff_timeline(request):
    """收付差异时间维度核心：按资金实际发生日把挂项目的预收/预付分摊到月/周桶。

    日期基准优先「收付明细」installment.occur_date（实际资金日），无明细回退记录
    occur_date；仍缺失者归入 null 桶。每期给出 预收发生/预付发生/本期差异/累计差异，
    并附每期内项目级拆分与逐笔明细。返回 dict（供 JSON 与导出共用）。
    入参：grain(month|week) start end(YYYY-MM-DD,可选) dept q(项目名,可选)。
    """
    grain = (request.GET.get('grain') or 'month').strip()
    if grain not in ('month', 'week'):
        grain = 'month'
    dept = (request.GET.get('dept') or '').strip()
    q = (request.GET.get('q') or '').strip().lower()

    def _pd(s):
        try:
            return datetime.date.fromisoformat(s) if s else None
        except ValueError:
            return None
    start = _pd((request.GET.get('start') or '').strip())
    end = _pd((request.GET.get('end') or '').strip())

    # 含散单（未挂项目）：归入「（未挂项目）」组，使月度预收/预付合计与资金池、
    # 现金流（含全部预收预付）对平——原 project__isnull=False 排除散单是逐月对不上的根因。
    qs = (_advance_dept_filter(AdvanceRecord.objects.select_related('project'), request)
          .prefetch_related('installments'))
    if dept:
        qs = qs.filter(delivery_dept=dept)

    # period_key -> {sort,label,in_total,out_total,projects:{name:{...}}}
    buckets = {}
    present = {}        # period_key -> (sort,label,anchor)，用于连续补桶
    null_bucket = {'in_total': Decimal('0'), 'out_total': Decimal('0'), 'projects': {}}
    has_null = False

    def _proj_slot(container, name, dept_name):
        return container.setdefault(name, {
            'project': name, 'dept': dept_name,
            'in_total': Decimal('0'), 'out_total': Decimal('0'),
            'in_items': [], 'out_items': [],
        })

    for a in qs.order_by('occur_date', 'id'):
        linked = bool(a.project and (a.project.short_name or '').strip())
        name = a.project.short_name.strip() if linked else '（未挂项目）'
        if q and (not linked or q not in name.lower()):
            continue
        dept_name = (a.project.delivery_dept if a.project else '') or a.delivery_dept or ''
        # 逐笔资金流：优先收付明细；无明细回退记录级单笔。余额标在记录最后一笔。
        insts = list(a.installments.all())
        if insts:
            flows = [{'date': i.occur_date, 'amount': i.amount or Decimal('0'),
                      'id': f'{a.id}-{i.id}'}
                     for i in sorted(insts, key=lambda x: (x.occur_date, x.install_no))]
        else:
            flows = [{'date': a.occur_date, 'amount': a.advance_amount or Decimal('0'),
                      'id': str(a.id)}]
        balance_left = a.balance_amount or Decimal('0')
        for idx, fl in enumerate(flows):
            d = fl['date']
            item = {
                'id': fl['id'],
                'occur_date': str(d) if d else '—',
                'amount': str(fl['amount']),
                'counterparty': a.counterparty or '—',
                'balance': str(balance_left) if idx == len(flows) - 1 else '0',
            }
            if d is None:
                if start or end:
                    continue    # 指定时间窗时，无日期记录无法归期 → 排除
                tgt, pslot = null_bucket, null_bucket['projects']
                has_null = True
            elif (start and d < start) or (end and d > end):
                continue        # 超出请求时间窗，跳过
            else:
                key, sort, label, anchor = _period_of(d, grain)
                present.setdefault(key, (sort, label, anchor))
                tgt = buckets.setdefault(key, {
                    'sort': sort, 'label': label,
                    'in_total': Decimal('0'), 'out_total': Decimal('0'), 'projects': {}})
                pslot = tgt['projects']
            slot = _proj_slot(pslot, name, dept_name)
            if a.direction == '预收':
                tgt['in_total'] += fl['amount']
                slot['in_total'] += fl['amount']
                slot['in_items'].append(item)
            else:
                tgt['out_total'] += fl['amount']
                slot['out_total'] += fl['amount']
                slot['out_items'].append(item)

    def _ser_projects(pdict):
        out = []
        for p in pdict.values():
            out.append({
                'project': p['project'], 'dept': p['dept'],
                'in_total': str(p['in_total']), 'out_total': str(p['out_total']),
                'diff': str(p['in_total'] - p['out_total']),
                'in_items': p['in_items'], 'out_items': p['out_items'],
            })
        out.sort(key=lambda x: abs(Decimal(x['diff'])), reverse=True)
        return out

    # 连续补桶 + 累计差异（按时间序滚动求和）
    seq = _fill_periods(present, grain)
    periods, cum = [], Decimal('0')
    t_in = t_out = Decimal('0')
    for key, label in seq:
        b = buckets.get(key)
        if b:
            bin_, bout = b['in_total'], b['out_total']
            projects = _ser_projects(b['projects'])
        else:
            bin_, bout, projects = Decimal('0'), Decimal('0'), []
        diff = bin_ - bout
        cum += diff
        t_in += bin_
        t_out += bout
        periods.append({
            'period': key, 'label': label,
            'in_total': str(bin_), 'out_total': str(bout),
            'diff': str(diff), 'cum_diff': str(cum),
            'projects': projects,
        })

    null_period = None
    if has_null:
        nin, nout = null_bucket['in_total'], null_bucket['out_total']
        null_period = {
            'in_total': str(nin), 'out_total': str(nout), 'diff': str(nin - nout),
            'projects': _ser_projects(null_bucket['projects']),
        }
        t_in += nin
        t_out += nout

    return {
        'grain': grain,
        'periods': periods,
        'null_period': null_period,
        'summary': {
            'in_total': str(t_in), 'out_total': str(t_out), 'diff': str(t_in - t_out),
            'cum_diff_end': str(cum), 'period_count': len(periods),
        },
    }


@csrf_exempt
@pk_required()
def advance_diff_timeline(request):
    """GET /advances/diff-timeline — 收付差异时间维度（月/周）分解。详见 _compute_diff_timeline。"""
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    denied = _ar_field_denied(request, 'adv_amount')   # 金额分析端点须有金额查看权
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    return ok(_compute_diff_timeline(request))


@csrf_exempt
@pk_required()
def advance_diff_timeline_export(request):
    """GET /advances/diff-timeline/export — 收付差异时间维度导出 Excel（时间汇总 + 项目明细两表）。"""
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    denied = _ar_field_denied(request, 'adv_amount')   # 金额分析端点须有金额查看权
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    data = _compute_diff_timeline(request)
    gl = '周' if data['grain'] == 'week' else '月'

    wb = openpyxl.Workbook()
    # Sheet 1：时间汇总
    ws1 = wb.active
    ws1.title = '时间汇总'
    _header_row(ws1, [f'{gl}份', '预收发生', '预付发生', '本期差异', '累计差异'], color='6A1B9A')
    for p in data['periods']:
        ws1.append([p['label'], float(p['in_total']), float(p['out_total']),
                    float(p['diff']), float(p['cum_diff'])])
    if data['null_period']:
        n = data['null_period']
        ws1.append(['日期未记录', float(n['in_total']), float(n['out_total']), float(n['diff']), ''])

    # Sheet 2：项目明细（每期 × 项目）
    ws2 = wb.create_sheet('项目明细')
    _header_row(ws2, [f'{gl}份', '项目简称', '交付部门', '预收发生', '预付发生', '本期差异'],
                color='6A1B9A')
    for p in data['periods']:
        for pr in p['projects']:
            ws2.append([p['label'], pr['project'], pr['dept'],
                        float(pr['in_total']), float(pr['out_total']), float(pr['diff'])])
    if data['null_period']:
        for pr in data['null_period']['projects']:
            ws2.append(['日期未记录', pr['project'], pr['dept'],
                        float(pr['in_total']), float(pr['out_total']), float(pr['diff'])])
    return _export_response(wb, f'收付差异-按{gl}.xlsx')


@csrf_exempt
@pk_required()
def advance_offset_workbench(request):
    """GET /advances/offset-workbench — 预收核销工作台（应收账款·预收核销 Tab）。

    按客户聚合：有未核销预收余额的客户 × 其名下仍有未收的应收明细，
    一屏看清「谁的预收还没用、能冲谁的账」，支持勾选批量核销。
    入参：dept(可选) q(客户名模糊,可选)
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    dept = (request.GET.get('dept') or '').strip()
    q = (request.GET.get('q') or '').strip()

    adv_qs = (_advance_dept_filter(AdvanceRecord.objects.select_related('project'), request)
              .filter(direction='预收', balance_amount__gt=0))
    if dept:
        adv_qs = adv_qs.filter(delivery_dept=dept)

    # 客户键：挂项目的取项目客户名，散单取往来单位
    groups = {}
    for a in adv_qs.order_by('occur_date', 'id'):
        cust = ((a.project.customer_name if a.project_id else a.counterparty) or '').strip()
        if not cust:
            continue
        if q and q.lower() not in cust.lower():
            continue
        g = groups.setdefault(cust, {'advances': [], 'records': [], '_proj_ids': set()})
        g['advances'].append({
            'id': a.id, 'counterparty': a.counterparty,
            'project_id': a.project_id,
            'short_name': a.project.short_name if a.project_id else None,
            'occur_date': str(a.occur_date) if a.occur_date else None,
            'balance_amount': str(a.balance_amount),
            'delivery_dept': a.delivery_dept,
        })
        if a.project_id:
            g['_proj_ids'].add(a.project_id)

    if not groups:
        return ok({'groups': [], 'total': 0})

    # 各客户名下仍有未收的应收（部门作用域内）
    rec_qs = (_ar_dept_filter(ARRecord.objects.select_related('project'), request,
                              shared_field='project__is_shared')
              .filter(outstanding_amount__gt=0,
                      project__customer_name__in=list(groups.keys())))
    if dept:
        rec_qs = rec_qs.filter(delivery_dept=dept)
    for r in rec_qs.order_by('operation_date', 'id'):
        cust = (r.project.customer_name or '').strip()
        if cust not in groups:
            continue
        groups[cust]['records'].append({
            'id': r.id, 'project_id': r.project_id,
            'short_name': r.project.short_name,
            'operation_date': str(r.operation_date) if r.operation_date else None,
            'due_date': str(r.due_date) if r.due_date else None,
            'estimated': str(r.estimated_amount or 0),
            'outstanding': str(r.outstanding_amount or 0),
            'delivery_dept': r.delivery_dept,
        })

    rows = []
    for cust, g in sorted(groups.items()):
        # 名下无可冲抵应收的分组（含散单往来单位名与客户名对不上的情况）直接丢弃，
        # 避免渲染「有预收却按钮恒置灰」的死卡片——本工作台只列「有预收且有未收」的客户
        if not g['records']:
            continue
        bal = sum(Decimal(a['balance_amount']) for a in g['advances'])
        out = sum(Decimal(r['outstanding']) for r in g['records'])
        rows.append({
            'customer': cust,
            'advances': g['advances'],
            'records': g['records'],
            'total_balance': str(bal),
            'total_outstanding': str(out),
            'offsettable': str(min(bal, out)),
        })
    # 有账可冲的排前面
    rows.sort(key=lambda x: Decimal(x['offsettable']), reverse=True)
    return ok({'groups': rows, 'total': len(rows)})


@csrf_exempt
@pk_required()
def advance_writeoff_detail(request, pk, wid):
    try:
        wo = AdvanceWriteoff.objects.select_related('advance_record__project').get(
            pk=wid, advance_record_id=pk)
    except AdvanceWriteoff.DoesNotExist:
        return err('核销记录不存在', 404)
    if request.pk_role != 'super_admin' and wo.advance_record.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    # 与 advance_writeoffs 同则：显式授予核销操作权限（出纳反向核销）越过页面/字段闸口
    _wo_action = 'wo_receive' if wo.advance_record.direction == '预收' else 'wo_prepaid'
    if not _action_granted(request, _wo_action):
        denied = _page_denied(request, 'ar_advance') or _ar_field_denied(request, 'adv_writeoff')
        if denied:
            return denied
    if request.method == 'PUT':
        denied = _action_denied(request, _wo_action)
        if denied:
            return denied
        data = _parse_body(request)
        try:
            # 全部上限校验搬进锁内：锁预收/预付行 + 关联排款行，与并发核销/退款/编辑串行。
            # 无锁校验会让两笔并发编辑各自通过「剩余待付/可核销余额」检查后合计超额。
            with transaction.atomic():
                adv_locked = AdvanceRecord.objects.select_for_update().get(pk=wo.advance_record_id)
                pay_obj = None
                if wo.payment_id:
                    from paikuan.models import Payment as _Payment
                    pay_obj = _Payment.objects.select_for_update().get(pk=wo.payment_id)
                new_amount = None
                if 'amount' in data:
                    new_amount = _dec(data['amount'])
                    if new_amount <= 0:
                        return err('核销金额必须大于0')
                    # 若该核销已生成「预收抵扣」回款，新金额不得超过应收可冲抵额
                    # （当前未收余额 + 本笔已冲抵额）。
                    if wo.ar_payment_id:
                        ar = wo.ar_payment.ar_record
                        available = (ar.outstanding_amount or Decimal('0')) + (wo.ar_payment.amount or Decimal('0'))
                        if new_amount > available:
                            return err(f'冲抵金额 {new_amount:,.2f} 超过该应收可冲抵额 {available:,.2f}')
                    # 预付侧同 create 口径：改大金额不得使 已付+累计冲抵 超过排款计划（待付为负）
                    if pay_obj is not None:
                        plan = (pay_obj.plan_adjustment if pay_obj.plan_adjustment is not None
                                else pay_obj.total_amount) or Decimal('0')
                        paid_amt = pay_obj.total_paid
                        offset_other = (pay_obj.prepaid_offset_amount or Decimal('0')) - (wo.amount or Decimal('0'))
                        room = plan - paid_amt - offset_other
                        if new_amount > room:
                            return err(f'冲抵金额 {new_amount:,.2f} 超过该排款剩余待付 {room:,.2f}'
                                       f'（计划 {plan} − 已付 {paid_amt} − 其它已冲抵 {offset_other}）')
                    # 预收/预付余额上限：其余核销不变时，本笔可用 = 当前未核销余额 + 本笔原额
                    adv_avail = ((adv_locked.balance_amount or Decimal('0'))
                                 + (wo.amount or Decimal('0')))
                    if new_amount > adv_avail:
                        return err(f'核销金额 {new_amount:,.2f} 超过可核销余额 {adv_avail:,.2f}')
                    wo.amount = new_amount
                if 'writeoff_date' in data:
                    _nd = _normalize_date(data['writeoff_date'])
                    if not _nd:
                        return err('核销日期无效（格式 2026-01-20）')
                    wo.writeoff_date = _nd
                if 'notes' in data:
                    wo.notes = (data['notes'] or '').strip()
                if wo.ar_payment_id and (new_amount is not None or 'writeoff_date' in data):
                    pay = wo.ar_payment
                    if new_amount is not None:
                        pay.amount = new_amount
                    pay.payment_date = wo.writeoff_date
                    pay.save()  # 触发应收 outstanding 重算
                wo.save()
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok(wo.to_dict())

    if request.method == 'DELETE':
        # 删核销 = 反向核销（撤销自己的操作），按核销操作权限把关，
        # 不要求通用删除权限——出纳能核销就能撤销自己的核销
        denied = _action_denied(request, _wo_action)
        if denied:
            return denied
        # 显式事务：核销删除会级联删「预收抵扣」回款并重算应收/预收，
        # 任一环失败需整体回滚，避免核销没了但回款还在的半套状态。
        try:
            with transaction.atomic():
                wo.delete()
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok({'deleted': wid})

    return err('Method not allowed', 405)






# ── 转移（往来单位间/项目间权益转移，非现金事件）──────────────────────────────

def _transfer_gate(request, rec):
    """转移通用闸：页面 + 部门 + 金额字段权限。"""
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    if request.pk_role != 'super_admin' and rec.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    return _ar_field_denied(request, 'adv_amount')


def _transfers_payload(rec_id):
    rec = AdvanceRecord.objects.select_related('project').get(pk=rec_id)
    sel = ('from_advance', 'from_advance__project', 'to_advance', 'to_advance__project', 'created_by')
    return {
        'transfers_in': [t.to_dict() for t in rec.transfers_in.select_related(*sel)],
        'transfers_out': [t.to_dict() for t in rec.transfers_out.select_related(*sel)],
        'advance_amount': str(rec.advance_amount),
        'transferred_in_amount': str(rec.transferred_in_amount),
        'transferred_out_amount': str(rec.transferred_out_amount),
        'written_off_amount': str(rec.written_off_amount),
        'balance_amount': str(rec.balance_amount),
        'writeoff_status': rec.writeoff_status,
        'aging_base_date': str(rec.aging_base_date) if rec.aging_base_date else None,
    }


@csrf_exempt
@pk_required()
def advance_transfers(request, pk):
    """GET/POST /advances/<pk>/transfers — 预收/预付转移。

    转移是权益重分类、非现金事件：不产生收付明细，现金流/区间收付统计不变；
    仅余额口径（recompute_derived）纳入转入/转出。目标侧账龄承袭源记录有效
    账龄起点。跨事业部转移仅超级管理员。"""
    try:
        rec = AdvanceRecord.objects.select_related('project').get(pk=pk)
    except AdvanceRecord.DoesNotExist:
        return err('记录不存在', 404)
    denied = _transfer_gate(request, rec)
    if denied:
        return denied

    if request.method == 'GET':
        return ok(_transfers_payload(rec.pk))

    if request.method != 'POST':
        return err('Method not allowed', 405)
    denied = _action_denied(request, 'adv_transfer')
    if denied:
        return denied
    data = _parse_body(request)
    amount = _dec(data.get('amount', 0))
    if amount <= 0:
        return err('转移金额必须大于0')
    tdate = _normalize_date(data.get('transfer_date'))
    if not tdate:
        return err('转移日期无效（格式 2026-01-20）')
    reason = (data.get('reason') or '').strip()
    if not reason:
        return err('请填写转移原因（如：合同主体变更/项目落位），以便日后追溯')
    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    try:
        with transaction.atomic():
            src = AdvanceRecord.objects.select_for_update().get(pk=pk)
            if amount > (src.balance_amount or Decimal('0')):
                return err(f'转移金额 {amount:,.2f} 超过源记录未核销余额 '
                           f'{(src.balance_amount or Decimal("0")):,.2f}')
            to_id = data.get('to_advance_id')
            new_target = None
            if to_id:
                try:
                    target = AdvanceRecord.objects.select_for_update().get(pk=int(to_id))
                except (AdvanceRecord.DoesNotExist, ValueError, TypeError):
                    return err('目标记录不存在')
                if target.pk == src.pk:
                    return err('不能转移给记录自身')
                if target.direction != src.direction:
                    return err(f'方向不一致：{src.direction} 只能转移到同方向记录')
                target_dept = target.delivery_dept
            else:
                nt = data.get('new_target') or {}
                cp = (nt.get('counterparty') or '').strip()
                if not cp:
                    return err('新建目标需填写往来单位')
                project = None
                if nt.get('project_id'):
                    try:
                        project = ARProject.objects.filter(pk=int(nt['project_id'])).first()
                    except (TypeError, ValueError):
                        return err('目标项目无效')
                    if not project:
                        return err('目标项目不存在')
                target_dept = (project.delivery_dept if project
                               else ((nt.get('delivery_dept') or '').strip() or src.delivery_dept))
                new_target = (cp, project)
            if target_dept != src.delivery_dept and request.pk_role != 'super_admin':
                return err('跨事业部转移仅超级管理员可操作', 403, 403)
            # 校验全部通过后才落库（return 不回滚事务，写入必须在所有校验之后）
            if new_target is not None:
                cp, project = new_target
                target = AdvanceRecord(
                    direction=src.direction, counterparty=cp, project=project,
                    delivery_dept=target_dept,
                    occur_year=src.occur_year, occur_month=src.occur_month,
                    occur_date=None, advance_amount=Decimal('0'),
                    expected_writeoff_date=src.expected_writeoff_date,
                    notes=f'由转移新建（源：{src.counterparty}）', created_by=user)
                target.save()
            AdvanceTransfer.objects.create(
                from_advance=src, to_advance=target, amount=amount,
                transfer_date=tdate, reason=reason[:200], created_by=user)
            src.recompute_derived()
            target.recompute_derived()
            target.recompute_aging_base()
    except ValidationError as e:
        return err(str(e.message if hasattr(e, 'message') else e), 400)
    return ok({**_transfers_payload(pk), 'target_id': target.pk})


@csrf_exempt
@pk_required()
def advance_transfer_detail(request, pk, tid):
    """DELETE /advances/<pk>/transfers/<tid> — 撤销转移（源/目标任一侧可发起）。

    守卫：撤销后目标余额不得为负（目标已核销/再转出转入款项时拒绝，提示先处理）。
    跨事业部单据仅超级管理员可撤销（与创建同权）。"""
    try:
        t = AdvanceTransfer.objects.select_related('from_advance', 'to_advance').get(pk=tid)
    except AdvanceTransfer.DoesNotExist:
        return err('转移记录不存在', 404)
    if pk not in (t.from_advance_id, t.to_advance_id):
        return err('转移记录不存在', 404)
    if request.method != 'DELETE':
        return err('Method not allowed', 405)
    gate_rec = t.from_advance if pk == t.from_advance_id else t.to_advance
    denied = _transfer_gate(request, gate_rec)
    if denied:
        return denied
    denied = _action_denied(request, 'adv_transfer')
    if denied:
        return denied
    if (t.from_advance.delivery_dept != t.to_advance.delivery_dept
            and request.pk_role != 'super_admin'):
        return err('跨事业部转移仅超级管理员可撤销', 403, 403)
    try:
        with transaction.atomic():
            src = AdvanceRecord.objects.select_for_update().get(pk=t.from_advance_id)
            tgt = AdvanceRecord.objects.select_for_update().get(pk=t.to_advance_id)
            if t.kind == 'cash_lines':
                d = t.detail or {}
                inst_ids = [x['id'] for x in d.get('installments', [])]
                wo_ids = [x['id'] for x in d.get('writeoffs', [])]
                insts = list(AdvanceInstallment.objects.select_for_update()
                             .filter(id__in=inst_ids, advance_record_id=tgt.pk))
                wos = list(AdvanceWriteoff.objects.select_for_update()
                           .filter(id__in=wo_ids, advance_record_id=tgt.pk))
                if len(insts) != len(inst_ids) or len(wos) != len(wo_ids):
                    return err('迁移的收付/核销行已在目标侧被修改或删除，无法撤销。请手工反向迁移更正')
                sp = d.get('wo_split')
                sp_moved = None
                if sp:
                    sp_moved = (AdvanceWriteoff.objects.select_for_update()
                                .filter(pk=sp['moved_id'], advance_record_id=tgt.pk).first())
                    if not sp_moved or str(sp_moved.amount) != sp['amount']:
                        return err('拆分随迁的核销已在目标侧被修改或删除，无法撤销。请手工反向迁移更正')
                inst_amt = sum((i.amount or Decimal('0')) for i in insts)
                wo_amt = (sum((w.amount or Decimal('0')) for w in wos)
                          + (Decimal(sp['amount']) if sp else Decimal('0')))
                # 撤销后目标余额 = 现余额 − 迁入收付 + 随迁核销
                if ((tgt.balance_amount or Decimal('0')) - inst_amt + wo_amt) < Decimal('0'):
                    return err('撤销后目标记录余额将为负（目标已使用迁入款项）。请先处理目标侧的核销或转移')
                orig_no = {x['id']: x.get('orig_no') for x in d.get('installments', [])}
                orig_wo_no = {x['id']: x.get('orig_no') for x in d.get('writeoffs', [])}
                note_tag = f'（自 {src.counterparty or "无往来单位"} 迁入）'
                used = set(src.installments.values_list('install_no', flat=True))
                nxt = (max(used) if used else 0)
                # 正额先行搬回：避免负额行先落导致源侧信号中间态误拒
                for i in sorted(insts, key=lambda x: (-(x.amount or Decimal('0')), x.install_no)):
                    want = orig_no.get(i.id)
                    if want and want not in used:
                        i.install_no = want
                    else:
                        nxt += 1
                        i.install_no = nxt
                    used.add(i.install_no)
                    i.advance_record = src
                    i.notes = (i.notes or '').replace(note_tag, '').strip()
                    i.save()
                used_w = set(src.writeoffs.values_list('writeoff_no', flat=True))
                nxt_w = (max(used_w) if used_w else 0)
                for w in wos:
                    want = orig_wo_no.get(w.id)
                    if want and want not in used_w:
                        w.writeoff_no = want
                    else:
                        nxt_w += 1
                        w.writeoff_no = nxt_w
                    used_w.add(w.writeoff_no)
                    w.advance_record = src
                    w.notes = (w.notes or '').replace(note_tag, '').strip()
                    w.save()
                if sp_moved is not None:
                    # 拆分复原：目标侧拆出行删除，金额拼回源核销行（源行已删则重建）。
                    # 重建取号必须感知 used_w（含按 orig_no 恢复的行），否则撞唯一键
                    portion = Decimal(sp['amount'])
                    src_row = (AdvanceWriteoff.objects.select_for_update()
                               .filter(pk=sp['src_id'], advance_record_id=src.pk).first())
                    sp_moved.delete()
                    if src_row is not None:
                        src_row.amount = (src_row.amount or Decimal('0')) + portion
                        src_row.save()
                    else:
                        rebuild_no = (max(used_w) if used_w else 0) + 1
                        used_w.add(rebuild_no)
                        AdvanceWriteoff.objects.create(
                            advance_record=src, writeoff_no=rebuild_no, amount=portion,
                            writeoff_date=_normalize_date(sp.get('writeoff_date'))
                            or timezone.localdate())
                t.delete()
                for r_ in (src, tgt):
                    r_.refresh_from_db()
                    r_.advance_amount = (r_.installments.aggregate(s=Sum('amount'))['s']
                                         or Decimal('0'))
                    AdvanceRecord.objects.filter(pk=r_.pk).update(advance_amount=r_.advance_amount)
                    r_.recompute_derived()
                tgt.recompute_aging_base()
            else:
                if (tgt.balance_amount or Decimal('0')) < (t.amount or Decimal('0')):
                    return err(f'撤销后目标记录余额将为负（目标已使用转入款项 '
                               f'{(t.amount or Decimal("0")):,.2f}）。请先处理目标侧的核销或转移，再撤销本单')
                t.delete()
                src.recompute_derived()
                tgt.recompute_derived()
                tgt.recompute_aging_base()
    except ValidationError as e:
        return err(str(e.message if hasattr(e, 'message') else e), 400)
    return ok(_transfers_payload(pk))


@csrf_exempt
@pk_required()
def advance_writeoff_migrate(request, pk, wid):
    """POST /advances/<pk>/writeoffs/<wid>/migrate {to_advance_id} — 核销记录迁移。

    核销挂错记录的更正通道：仅限「纯登记核销」（未关联预收抵扣回款/排款）；
    关联型核销须先撤销关联再按正常流程处理。目标余额须足以承接该笔核销。"""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    try:
        wo = AdvanceWriteoff.objects.select_related('advance_record').get(
            pk=wid, advance_record_id=pk)
    except AdvanceWriteoff.DoesNotExist:
        return err('核销记录不存在', 404)
    src_rec = wo.advance_record
    denied = _transfer_gate(request, src_rec)
    if denied:
        return denied
    denied = _action_denied(request, 'adv_transfer')
    if denied:
        return denied
    if wo.ar_record_id or wo.ar_payment_id or wo.payment_id:
        return err('该核销已关联预收抵扣回款/排款，不能直接迁移：'
                   '请先删除该核销解除关联，将余额转移到目标记录后重新核销')
    data = _parse_body(request)
    try:
        to_id = int(data.get('to_advance_id'))
    except (TypeError, ValueError):
        return err('目标记录无效')
    try:
        with transaction.atomic():
            src = AdvanceRecord.objects.select_for_update().get(pk=pk)
            # 锁内复检：并发的按笔迁移可能已把该核销整移/拆小——重取新鲜行，
            # 陈旧对象直接 save 会把核销抢回或金额写回，造成双计
            wo = (AdvanceWriteoff.objects.select_for_update()
                  .filter(pk=wid, advance_record_id=src.pk).first())
            if wo is None:
                return err('该核销已被并发操作移动或删除，请刷新后重试')
            if wo.ar_record_id or wo.ar_payment_id or wo.payment_id:
                return err('该核销已关联预收抵扣回款/排款，不能直接迁移：'
                           '请先删除该核销解除关联，将余额转移到目标记录后重新核销')
            try:
                tgt = AdvanceRecord.objects.select_for_update().get(pk=to_id)
            except AdvanceRecord.DoesNotExist:
                return err('目标记录不存在')
            if tgt.pk == src.pk:
                return err('目标不能是当前记录')
            if tgt.direction != src.direction:
                return err(f'方向不一致：{src.direction} 核销只能迁移到同方向记录')
            if (tgt.delivery_dept != src.delivery_dept
                    and request.pk_role != 'super_admin'):
                return err('跨事业部迁移仅超级管理员可操作', 403, 403)
            if (tgt.balance_amount or Decimal('0')) < (wo.amount or Decimal('0')):
                return err(f'目标记录未核销余额 {(tgt.balance_amount or Decimal("0")):,.2f} '
                           f'不足以承接该笔核销 {(wo.amount or Decimal("0")):,.2f}')
            next_no = (tgt.writeoffs.aggregate(m=Max("writeoff_no"))["m"] or 0) + 1
            note_tag = f'（自 {src.counterparty or "无往来单位"} 迁入）'
            wo.advance_record = tgt
            wo.writeoff_no = next_no
            if note_tag not in (wo.notes or ''):
                wo.notes = ((wo.notes or '') + note_tag).strip()
            wo.save()
            src.recompute_derived()
            tgt.recompute_derived()
    except ValidationError as e:
        return err(str(e.message if hasattr(e, 'message') else e), 400)
    return ok({'moved': True, 'from': _transfers_payload(pk), 'to': _transfers_payload(to_id)})

@csrf_exempt
@pk_required()
def advance_installments_migrate(request, pk):
    """POST /advances/<pk>/installments/migrate — 按笔迁移收付明细（可连带核销）。

    body: {installment_ids: [..], writeoff_ids: [..]?, reason,
           transfer_date?, to_advance_id | new_target{counterparty, project_id?}}

    与「权益划转」互补的第二种转移语义：这笔收付当初就记错了对象 → 把选中的
    收付行（及可选的纯登记核销行）整笔物理迁移到目标记录，收付日期/金额随行，
    现金口径同步更正。守卫：双侧余额均不得为负（源侧核销覆盖被迁收付时须
    连带迁核销或先撤核销）；关联型核销不可随迁；跨事业部仅超管；整个操作
    原子且可整单撤销（DELETE 对应转移单）。"""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    try:
        rec = AdvanceRecord.objects.select_related('project').get(pk=pk)
    except AdvanceRecord.DoesNotExist:
        return err('记录不存在', 404)
    denied = _transfer_gate(request, rec)
    if denied:
        return denied
    denied = _action_denied(request, 'adv_transfer')
    if denied:
        return denied
    data = _parse_body(request)
    inst_ids = data.get('installment_ids') or []
    if not isinstance(inst_ids, list) or not inst_ids:
        return err('请选择要迁移的收付明细')
    wo_ids = data.get('writeoff_ids') or []
    if not isinstance(wo_ids, list):
        return err('核销参数无效')
    try:
        inst_ids = [int(x) for x in inst_ids]
        wo_ids = [int(x) for x in wo_ids]
    except (TypeError, ValueError):
        return err('明细参数无效')
    # 核销随迁模式：auto=自动同步（默认，FIFO 取纯登记核销 min(迁移额, 已核销)，
    # 边界行自动拆分——已核销覆盖的部分整体平移，源未核销余额尽量不变）；
    # none=仅迁收付；manual=显式 writeoff_ids（兼容旧调用）
    carry_mode = (data.get('carry_mode') or ('manual' if wo_ids else 'auto')).strip()
    if carry_mode not in ('auto', 'none', 'manual'):
        return err('核销随迁模式无效')
    if carry_mode != 'manual' and wo_ids:
        return err('carry_mode 为 auto/none 时不能同时指定 writeoff_ids（二者语义冲突）')
    reason = (data.get('reason') or '').strip()
    if not reason:
        return err('请填写迁移原因（如：收付登记错对象），以便日后追溯')
    tdate = _normalize_date(data.get('transfer_date')) or timezone.localdate()
    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    try:
        with transaction.atomic():
            src = AdvanceRecord.objects.select_for_update().get(pk=pk)
            insts = list(AdvanceInstallment.objects.select_for_update()
                         .filter(id__in=inst_ids, advance_record_id=src.pk))
            if len(insts) != len(set(inst_ids)):
                return err('部分收付明细不存在或不属于本记录')
            inst_amt = sum((i.amount or Decimal('0')) for i in insts)
            # 转移单金额约束 amount>0：净额非正的选择（仅退回行/正负抵零）不可单独迁，
            # 退回行须与其对应的正额收付一起选中迁移
            if inst_amt <= Decimal('0'):
                return err(f'所选收付净额为 {inst_amt:,.2f}，必须大于0：'
                           '退回（负额）行请与对应的正额收付行一起勾选迁移')
            split_plan = None   # (源核销行, 拆出金额)
            if carry_mode == 'manual':
                wos = list(AdvanceWriteoff.objects.select_for_update()
                           .filter(id__in=wo_ids, advance_record_id=src.pk))
                if len(wos) != len(set(wo_ids)):
                    return err('部分核销记录不存在或不属于本记录')
                for w in wos:
                    if w.ar_record_id or w.ar_payment_id or w.payment_id:
                        return err(f'第{w.writeoff_no}笔核销已关联预收抵扣回款/排款，不可随迁：'
                                   '请先删除该核销解除关联后重试')
                wo_amt = sum((w.amount or Decimal('0')) for w in wos)
            elif carry_mode == 'none':
                wos = []
                wo_amt = Decimal('0')
            else:   # auto
                carry_target = min(inst_amt, src.written_off_amount or Decimal('0'))
                pure = list(AdvanceWriteoff.objects.select_for_update()
                            .filter(advance_record_id=src.pk, ar_record__isnull=True,
                                    ar_payment__isnull=True, payment__isnull=True)
                            .order_by('writeoff_date', 'writeoff_no', 'id'))
                remaining = carry_target
                wos = []
                for w in pure:
                    if remaining <= Decimal('0'):
                        break
                    amt = w.amount or Decimal('0')
                    if amt <= remaining:
                        wos.append(w)
                        remaining -= amt
                    else:
                        split_plan = (w, remaining)
                        remaining = Decimal('0')
                wo_amt = carry_target - remaining   # 纯核销池不足时只随迁可迁部分
            # 源侧：移走收付、随迁核销后余额不得为负
            src_after = (src.balance_amount or Decimal('0')) - inst_amt + wo_amt
            if src_after < Decimal('0'):
                need = -src_after
                # 精确定位缺口成因：退款冲抵 / 关联型核销（预收抵扣、排款）/ 需连带纯核销
                refund_amt = src.refunded_amount or Decimal('0')
                linked_wo = ((src.written_off_amount or Decimal('0'))
                             - sum((w.amount or Decimal('0')) for w in wos)
                             - (split_plan[1] if split_plan else Decimal('0')))
                causes = []
                if refund_amt > 0:
                    causes.append(f'已退款 {refund_amt:,.2f}（退款为供应商退回的现金，'
                                  '不随迁移转移；如供应商确已变更，请先在日常收款解除该退款关联）')
                if linked_wo > 0:
                    causes.append(f'已关联预收抵扣回款/排款的核销 {linked_wo:,.2f}'
                                  '（请先撤销对应关联核销）')
                if carry_mode != 'auto' and not causes:
                    causes.append(f'被迁收付已被核销覆盖，请连带迁移约 {need:,.2f} 的纯登记核销，'
                                  '或改用自动同步模式')
                tail = '；'.join(causes) if causes else '被迁收付已被其它记录占用'
                return err(f'迁移后源记录余额将为负 {src_after:,.2f}，无法迁移：该笔收付有 '
                           f'{need:,.2f} 由以下方式冲抵、不能随迁——{tail}')
            # 目标：已有 or 新建（校验先行，写入殿后——return 不回滚事务）
            to_id = data.get('to_advance_id')
            new_target = None
            if to_id:
                try:
                    target = AdvanceRecord.objects.select_for_update().get(pk=int(to_id))
                except (AdvanceRecord.DoesNotExist, ValueError, TypeError):
                    return err('目标记录不存在')
                if target.pk == src.pk:
                    return err('不能迁移到记录自身')
                if target.direction != src.direction:
                    return err(f'方向不一致：{src.direction} 只能迁移到同方向记录')
                target_dept = target.delivery_dept
            else:
                nt = data.get('new_target') or {}
                cp = (nt.get('counterparty') or '').strip()
                if not cp:
                    return err('新建目标需填写往来单位')
                project = None
                if nt.get('project_id'):
                    try:
                        project = ARProject.objects.filter(pk=int(nt['project_id'])).first()
                    except (TypeError, ValueError):
                        return err('目标项目无效')
                    if not project:
                        return err('目标项目不存在')
                target_dept = (project.delivery_dept if project
                               else ((nt.get('delivery_dept') or '').strip() or src.delivery_dept))
                new_target = (cp, project)
            if target_dept != src.delivery_dept and request.pk_role != 'super_admin':
                return err('跨事业部迁移仅超级管理员可操作', 403, 403)
            # 目标侧余额守卫先行（新建目标初始余额为0）：err 返回不回滚事务，
            # 一切校验必须发生在任何写入之前，否则会留下孤儿目标记录
            _tgt_bal_before = (Decimal('0') if new_target is not None
                               else (target.balance_amount or Decimal('0')))
            tgt_after = _tgt_bal_before + inst_amt - wo_amt
            if tgt_after < Decimal('0'):
                return err(f'迁移后目标记录余额将为负 {tgt_after:,.2f}：随迁核销超过迁入收付与目标余额之和')
            if new_target is not None:
                cp, project = new_target
                target = AdvanceRecord(
                    direction=src.direction, counterparty=cp, project=project,
                    delivery_dept=target_dept,
                    occur_year=src.occur_year, occur_month=src.occur_month,
                    occur_date=None, advance_amount=Decimal('0'),
                    expected_writeoff_date=src.expected_writeoff_date,
                    notes=f'由迁移新建（源：{src.counterparty}）', created_by=user)
                target.save()
            # ── 落库：移动行 + 记转移单（cash_lines）──
            note_tag = f'（自 {src.counterparty or "无往来单位"} 迁入）'
            detail = {'installments': [], 'writeoffs': [],
                      'carry_mode': carry_mode,
                      'wo_amount': str(wo_amt),
                      # 账龄承袭基准只看正额收付（退回行不该把账龄钉早）
                      'earliest_date': str(min(i.occur_date for i in insts
                                               if (i.amount or Decimal('0')) > 0))}
            used = set(target.installments.values_list('install_no', flat=True))
            nxt = (max(used) if used else 0)
            # 正额先行：混合正负时先抬高目标余额再落负额行，避免信号中间态误拒
            for i in sorted(insts, key=lambda x: (-(x.amount or Decimal('0')), x.install_no)):
                detail['installments'].append({'id': i.id, 'orig_no': i.install_no})
                nxt += 1
                i.install_no = nxt
                i.advance_record = target
                if note_tag not in (i.notes or ''):
                    i.notes = ((i.notes or '') + note_tag).strip()
                i.save()
            used_w = set(target.writeoffs.values_list('writeoff_no', flat=True))
            nxt_w = (max(used_w) if used_w else 0)
            for w in sorted(wos, key=lambda x: x.writeoff_no):
                detail['writeoffs'].append({'id': w.id, 'orig_no': w.writeoff_no})
                nxt_w += 1
                w.writeoff_no = nxt_w
                w.advance_record = target
                if note_tag not in (w.notes or ''):
                    w.notes = ((w.notes or '') + note_tag).strip()
                w.save()
            if split_plan is not None:
                sw, portion = split_plan
                sw.amount = (sw.amount or Decimal('0')) - portion
                sw.save()
                nxt_w += 1
                moved = AdvanceWriteoff.objects.create(
                    advance_record=target, writeoff_no=nxt_w, amount=portion,
                    writeoff_date=sw.writeoff_date,
                    notes=(((sw.notes or '') + note_tag).strip()))
                detail['wo_split'] = {'src_id': sw.id, 'moved_id': moved.id,
                                      'amount': str(portion),
                                      'writeoff_date': str(sw.writeoff_date)}
            AdvanceTransfer.objects.create(
                from_advance=src, to_advance=target, kind='cash_lines',
                amount=inst_amt, transfer_date=tdate, reason=reason[:200],
                detail=detail, created_by=user)
            for r_ in (src, target):
                r_.refresh_from_db()
                r_.advance_amount = (r_.installments.aggregate(s=Sum('amount'))['s']
                                     or Decimal('0'))
                AdvanceRecord.objects.filter(pk=r_.pk).update(advance_amount=r_.advance_amount)
                r_.recompute_derived()
            target.recompute_aging_base()
    except ValidationError as e:
        return err(str(e.message if hasattr(e, 'message') else e), 400)
    return ok({**_transfers_payload(pk), 'target_id': target.pk})


# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
