"""应收记录（AR records）业务域视图：记录台账 CRUD/导入导出、KPI、回款流水、
分组汇总、催收工作台与催办、回款与调整、对账数据健康、批量重算/删除。
共享导入·常量·过滤助手等来自 _common。"""
from ._common import *  # noqa: F401,F403
from paikuan.list_filters import build_filter_q, resolve_sort

# ── 应收明细 Excel 风格列头筛选 + 排序白名单 ─────────────────────────────────
# 仅登记【真实存储列】（含项目 FK 上的文本列，multi 需去重）；计算/派生/聚合列
# （对账状态、开票状态、责任状态、回款笔数、预收冲抵等）一律不登记，留待后续阶段。
# 与既有 flat 维度筛选 / conditions / _apply_record_sort 并存，互不影响。
ARRECORD_FILTER_REGISTRY = {
    # 文本（项目 FK 文本列：反向 JOIN 需 distinct）
    'customer_name':      {'type': 'text', 'col': 'project__customer_name', 'multi': True},
    'short_name':         {'type': 'text', 'col': 'project__short_name', 'multi': True},
    'project_no':         {'type': 'text', 'col': 'project__project_no', 'multi': True},
    'invoice_batch_no':   {'type': 'text', 'col': 'invoice_batch_no'},
    'notes':              {'type': 'text', 'col': 'notes'},
    # 枚举（ARRecord 上的去规范化部门列，真实存储）
    'delivery_dept':      {'type': 'enum', 'col': 'delivery_dept'},
    # 日期（均为真实存储 DateField）
    'operation_date':     {'type': 'date', 'col': 'operation_date'},
    'due_date':           {'type': 'date', 'col': 'due_date'},
    'invoice_date':       {'type': 'date', 'col': 'invoice_date'},
    'reconciliation_date':{'type': 'date', 'col': 'reconciliation_date'},
    'target_collection_date': {'type': 'date', 'col': 'target_collection_date'},
    # 数值（均为真实存储 DecimalField，非注解/计算）
    'estimated_amount':       {'type': 'number', 'col': 'estimated_amount'},
    'actual_invoice_amount':  {'type': 'number', 'col': 'actual_invoice_amount'},
    'tax_amount':             {'type': 'number', 'col': 'tax_amount'},
    'account_diff_adjustment':{'type': 'number', 'col': 'account_diff_adjustment'},
    'outstanding_amount':     {'type': 'number', 'col': 'outstanding_amount'},
}


def _apply_colfilter_sort(qs, request):
    """应用列头筛选(filters JSON) + 列头排序(sort/order)。

    放在既有筛选之后、分页之前；与 flat 维度/状态筛选、_apply_record_sort 叠加。
    列头排序仅在命中白名单时生效，否则不动既有排序结果。"""
    fq, fq_distinct = build_filter_q(request.GET.get('filters', ''), ARRECORD_FILTER_REGISTRY)
    if fq:
        qs = qs.filter(fq)
        if fq_distinct:
            qs = qs.distinct()
    sort_by = resolve_sort(request.GET.get('sort'), request.GET.get('order'),
                           ARRECORD_FILTER_REGISTRY)
    if sort_by:
        qs = qs.order_by(sort_by)
    return qs

# ══════════════════════════════════════════════════════════════════════════════
# AR Records
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@pk_required()
def ar_records_date_bounds(request):
    """Return min/max payment_date across all accessible AR records.

    Used by the frontend to constrain the pay-date range picker so users
    don't see decades of empty calendar space.
    """
    if request.method != 'GET':
        return err('GET only', 405)
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    qs = _ar_dept_filter(ARRecord.objects.all(), request,
                         shared_field='project__is_shared')
    pay_qs = ARPayment.objects.filter(ar_record__in=qs)
    bounds = pay_qs.aggregate(mn=Min('payment_date'), mx=Max('payment_date'))
    mn = bounds['mn']
    mx = bounds['mx']
    # Fallback: derive from operation_year/month when no payments exist
    if mn is None:
        rec_b = qs.aggregate(miny=Min('operation_year'), minm=Min('operation_month'),
                              maxy=Max('operation_year'), maxm=Max('operation_month'))
        if rec_b['miny']:
            mn = datetime.date(rec_b['miny'], rec_b['minm'] or 1, 1)
        if rec_b['maxy']:
            import calendar as _cal
            m = rec_b['maxm'] or 12
            mn = mn or datetime.date(rec_b['miny'] or rec_b['maxy'], 1, 1)
            mx = datetime.date(rec_b['maxy'], m, _cal.monthrange(rec_b['maxy'], m)[1])
    return ok({
        'min': str(mn) if mn else None,
        'max': str(mx) if mx else None,
    })


@csrf_exempt
@pk_required()
def ar_records(request):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied

    if request.method == 'GET':
        today = datetime.date.today()
        # Listing queryset — select_related for efficient to_dict() rendering
        qs = _ar_dept_filter(ARRecord.objects.select_related('project', 'created_by'), request,
                             shared_field='project__is_shared')
        qs = _apply_record_filters(qs, request)
        qs = _apply_record_state_filters(qs, request, today)
        qs = _apply_conditions(qs, request, today)
        qs = _apply_record_sort(qs, request)
        # 列头筛选 + 列头排序（真实列白名单）：叠加在既有筛选/排序之后
        qs = _apply_colfilter_sort(qs, request)

        include_payments = request.GET.get('include_payments', '') in ('1', 'true')
        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))

        # Aggregate queryset — plain queryset (no select_related) avoids any
        # accidental extra JOINs and keeps results consistent with the group-summary
        # endpoint which also uses ARRecord.objects.all() as its base.
        qs_agg = _ar_dept_filter(ARRecord.objects.all(), request,
                                 shared_field='project__is_shared')
        qs_agg = _apply_record_filters(qs_agg, request)
        qs_agg = _apply_record_state_filters(qs_agg, request, today)
        qs_agg = _apply_conditions(qs_agg, request, today)
        # 列头筛选同步进合计集，使"筛选即合计"summary 与可见列表口径一致
        # （排序对 aggregate 无意义，故只取 filters，不取 sort）
        _fq, _fq_distinct = build_filter_q(request.GET.get('filters', ''), ARRECORD_FILTER_REGISTRY)
        if _fq:
            qs_agg = qs_agg.filter(_fq)
            if _fq_distinct:
                qs_agg = qs_agg.distinct()

        # 当前筛选全集的金额合计（不止当前页）——支撑"筛选即合计"。
        # 重要：筛选含 payments 关联（回款日期/含未结清）时 qs_agg 带 JOIN，直接
        # aggregate 会把每条记录的金额按其回款笔数重复累加。改用「无 JOIN 基表 +
        # id IN (子查询)」：DB 端去重，避免把全量 id 拉进内存（大数据量下的热点）。
        matched_ids = qs_agg.order_by().values('id')
        base = ARRecord.objects.filter(id__in=matched_ids)
        total = base.count()
        # Only sum outstanding_amount where > 0: matches the table which renders
        # non-positive rows as "—" (settled/overpaid treated identically as 0).
        agg = base.aggregate(
            est=Sum('estimated_amount'),
            inv=Sum('actual_invoice_amount'),
            tax=Sum('tax_amount'),
            out=Sum('outstanding_amount', filter=Q(outstanding_amount__gt=0)),
            adj=Sum('account_diff_adjustment'),
        )
        collected = (ARPayment.objects.filter(ar_record_id__in=matched_ids)
                     .aggregate(s=Sum('amount'))['s'] or 0)

        # ── 时段合计：本月应收/已收 + 本周应收/已收 ─────────────────────────
        # 基准日期 = 所有日期筛选里最晚的一天（都没选则用今天）
        # 注意：today 不加入候选集，只在没有任何筛选时作为兜底；
        # 否则历史月份筛选（如 2024年3月）会被今天覆盖，导致窗口不联动。
        ref_candidates = []
        year_f = request.GET.get('year', '').strip()
        month_f = request.GET.get('month', '').strip()
        pay_end_f = request.GET.get('pay_end', '').strip()
        if year_f:
            try:
                y_i = int(year_f)
                m_i = int(month_f) if month_f else 12
                ref_candidates.append(
                    datetime.date(y_i, m_i, calendar.monthrange(y_i, m_i)[1]))
            except (ValueError, OverflowError):
                pass
        if pay_end_f:
            try:
                ref_candidates.append(datetime.date.fromisoformat(pay_end_f))
            except ValueError:
                pass
        ref_date = max(ref_candidates) if ref_candidates else today

        # 自然月窗口
        mo_start = datetime.date(ref_date.year, ref_date.month, 1)
        mo_end = datetime.date(ref_date.year, ref_date.month,
                               calendar.monthrange(ref_date.year, ref_date.month)[1])
        # 周窗口（业务口径：周五 ~ 次周周四）。Friday=weekday 4。
        wk_start = ref_date - datetime.timedelta(days=(ref_date.weekday() - 4) % 7)
        wk_end = wk_start + datetime.timedelta(days=6)
        # 上一周（同口径，用于环比比对）
        prev_wk_start = wk_start - datetime.timedelta(days=7)
        prev_wk_end = wk_start - datetime.timedelta(days=1)
        # 周标签随基准日联动：基准周==今天所在周时叫"本周"，否则叫"该周"
        today_wk_start = today - datetime.timedelta(days=(today.weekday() - 4) % 7)
        week_label = '本周' if wk_start == today_wk_start else '该周'

        # 应收（净额口径）：按 due_date 落在窗口内的记录，取「预估上账 − 该批已回款」，
        # 这样分批回款的记录只显示尚未收回的真实应收，不再用毛预估虚高。
        # 调整：同一窗口（按 due_date）记录的账实差额合计，单列展示；
        #       恒等式 应收(净) + 调整 = 未收(outstanding)。
        def _period_est_adj(recs):
            gross = recs.aggregate(s=Sum('estimated_amount'))['s'] or 0
            paid = (ARPayment.objects.filter(ar_record__in=recs)
                    .aggregate(s=Sum('amount'))['s'] or 0)
            adj = recs.aggregate(s=Sum('account_diff_adjustment'))['s'] or 0
            return gross - paid, adj
        # 当期：due_date 落在基准月内
        month_curr_est, month_curr_adjust = _period_est_adj(
            base.filter(due_date__gte=mo_start, due_date__lte=mo_end))
        # 逾期应收：due_date 早于基准月且仍有未收余额，取 outstanding_amount 之和
        month_overdue_est = (base.filter(due_date__lt=mo_start, outstanding_amount__gt=0)
                             .aggregate(s=Sum('outstanding_amount'))['s'] or 0)
        week_est, week_adjust = _period_est_adj(
            base.filter(due_date__gte=wk_start, due_date__lte=wk_end))

        # 已收：按 payment_date 落在窗口内，限当前筛选记录集
        # 当期已收：回款记录所属的 AR 明细到期日 >= 基准月首日（当期或未来到期）
        # 逾期已收：回款记录所属的 AR 明细到期日 <  基准月首日（逾期后补收）
        # 两者之和 = 旧的 month_collected（本月全部实收）
        pay_in_set = ARPayment.objects.filter(ar_record_id__in=matched_ids)
        pay_in_month = pay_in_set.filter(payment_date__gte=mo_start, payment_date__lte=mo_end)
        month_curr_collected = (pay_in_month
                                .filter(ar_record__due_date__gte=mo_start)
                                .aggregate(s=Sum('amount'))['s'] or 0)
        month_overdue_collected = (pay_in_month
                                   .filter(ar_record__due_date__lt=mo_start)
                                   .aggregate(s=Sum('amount'))['s'] or 0)
        week_collected = (pay_in_set
                          .filter(payment_date__gte=wk_start, payment_date__lte=wk_end)
                          .aggregate(s=Sum('amount'))['s'] or 0)
        # 上周（环比）：应收(净)/调整按 due_date、已收按 payment_date 落在上周窗口
        prev_week_est, prev_week_adjust = _period_est_adj(
            base.filter(due_date__gte=prev_wk_start, due_date__lte=prev_wk_end))
        prev_week_collected = (pay_in_set
                               .filter(payment_date__gte=prev_wk_start, payment_date__lte=prev_wk_end)
                               .aggregate(s=Sum('amount'))['s'] or 0)

        summary = {
            'count': total,
            'estimated': str(agg['est'] or 0),
            'invoiced': str(agg['inv'] or 0),
            'tax': str(agg['tax'] or 0),
            'outstanding': str(agg['out'] or 0),
            'adj': str(agg['adj'] or 0),
            'collected': str(collected),
            'month_curr_est': str(month_curr_est),
            'month_curr_adjust': str(month_curr_adjust),
            'month_curr_collected': str(month_curr_collected),
            'month_overdue_est': str(month_overdue_est),
            'month_overdue_collected': str(month_overdue_collected),
            'week_est': str(week_est),
            'week_adjust': str(week_adjust),
            'week_collected': str(week_collected),
            'prev_week_est': str(prev_week_est),
            'prev_week_adjust': str(prev_week_adjust),
            'prev_week_collected': str(prev_week_collected),
            'ref_date': ref_date.isoformat(),
            'ref_month': f'{ref_date.year}年{ref_date.month}月',
            'ref_week': f'{wk_start.month}/{wk_start.day}~{wk_end.month}/{wk_end.day}',
            'prev_ref_week': f'{prev_wk_start.month}/{prev_wk_start.day}~{prev_wk_end.month}/{prev_wk_end.day}',
            'ref_week_label': week_label,
        }
        items = list(qs[(page - 1) * size: page * size])

        perms = get_request_perms(request)
        if include_payments:
            # Prefetch payments
            record_ids = [r.id for r in items]
            pay_qs = ARPayment.objects.filter(ar_record_id__in=record_ids).order_by('payment_no')
            pay_map = defaultdict(list)
            for p in pay_qs:
                pay_map[p.ar_record_id].append(p.to_dict())
            # Prefetch adjustments（编辑态需带出已有差额调整明细以便删除）
            adj_qs = ARAdjustment.objects.filter(ar_record_id__in=record_ids)
            adj_map = defaultdict(list)
            for a in adj_qs:
                adj_map[a.ar_record_id].append(a.to_dict())
            rows = []
            for r in items:
                d = r.to_dict(today=today)
                d['payments'] = pay_map.get(r.id, [])
                d['adjustments'] = adj_map.get(r.id, [])
                rows.append(apply_ar_view_mask(d, perms, 'record'))
        else:
            rows = [apply_ar_view_mask(r.to_dict(today=today), perms, 'record') for r in items]

        return ok({'items': rows, 'total': total, 'page': page, 'size': size,
                   'summary': summary})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _ar_visible_payload(
            request, _parse_body(request), 'record',
            extra=('project_id', 'operation_date', 'operation_year', 'operation_month'))
        project_id = data.get('project_id')
        if not project_id:
            return err('缺少 project_id')
        try:
            proj = ARProject.objects.get(pk=int(project_id))
        except ARProject.DoesNotExist:
            return err('项目不存在', 404)
        denied = _dept_denied(request, proj.delivery_dept, '无权操作此部门')
        if denied:
            return denied
        # 运作日期为正源；兼容旧调用方只传年/月（默认当月1日）
        op_raw = _normalize_date(data.get('operation_date'))
        try:
            op_date = datetime.date.fromisoformat(op_raw) if op_raw else None
        except ValueError:
            op_date = None
        if not op_date:
            year = int(data.get('operation_year', 0) or 0)
            month = int(data.get('operation_month', 0) or 0)
            if not (year and 1 <= month <= 12):
                return err('运作日期无效：请提供 operation_date（YYYY-MM-DD）')
            op_date = datetime.date(year, month, 1)
        if not (2000 <= op_date.year <= 2100):
            return err('运作日期超出合理范围（2000–2100）')
        from paikuan.models import PaikuanUser
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        try:
            rec = ARRecord(
                project=proj,
                operation_date=op_date,
                estimated_amount=_dec(data.get('estimated_amount', 0)),
                actual_invoice_amount=_dec(data['actual_invoice_amount']) if data.get('actual_invoice_amount') not in (None, '') else None,
                tax_amount=_dec(data['tax_amount']) if data.get('tax_amount') not in (None, '') else None,
                invoice_date=_normalize_date(data.get('invoice_date')) or None,
                target_collection_date=_normalize_date(data.get('target_collection_date')) or None,
                reconciliation_date=_normalize_date(data.get('reconciliation_date')) or None,
                notes=data.get('notes', '').strip(),
                created_by=user,
            )
            # 已填开票金额必须有开票日期：开票状态/到期推算都依赖日期，缺日期会出现
            # 「已开票却无法算账期」的悬空状态
            if rec.actual_invoice_amount is not None and not rec.invoice_date:
                return err('已填实际开票金额，请同时填写开票日期')
            rec.save()
            # 差额调整走明细：创建时带差额 → 生成一条调整明细（原因可一并提交），
            # account_diff_adjustment 由信号派生为明细合计
            init_diff = _dec(data.get('account_diff_adjustment', 0))
            if init_diff:
                ARAdjustment.objects.create(
                    ar_record=rec, amount=init_diff,
                    reason=(data.get('adjustment_reason') or '').strip() or '录入时调整',
                    created_by=user)
                rec.refresh_from_db()
        except Exception as e:
            return err(str(e))
        return ok(apply_ar_view_mask(
            rec.to_dict(today=datetime.date.today(), include_payments=True),
            get_request_perms(request), 'record'))

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_record_detail(request, pk):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    try:
        rec = ARRecord.objects.select_related('project', 'created_by').get(pk=pk)
    except ARRecord.DoesNotExist:
        return err('记录不存在', 404)
    if request.pk_role != 'super_admin':
        allowed = request.pk_depts
        if rec.delivery_dept not in allowed:
            return err('无权访问', 403)
        perms = get_request_perms(request)
        if perms and perms.get('ar_shared_only') and not rec.project.is_shared:
            return err('无权访问', 403)

    today = datetime.date.today()

    if request.method == 'GET':
        return ok(apply_ar_view_mask(rec.to_dict(today=today, include_payments=True),
                                     get_request_perms(request), 'record'))

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _ar_visible_payload(request, _parse_body(request), 'record',
                                   extra=('operation_date',))
        # 运作日期可改：变更后同步重算应收日期(due_date，由运作日期+项目账期派生)；
        # 目标回款日期(target_collection_date)为手工值，不随之变动。
        if 'operation_date' in data:
            op_raw = _normalize_date(data['operation_date'])
            try:
                new_op = datetime.date.fromisoformat(op_raw) if op_raw else None
            except ValueError:
                new_op = None
            if not new_op:
                return err('运作日期无效：请提供 operation_date（YYYY-MM-DD）')
            if not (2000 <= new_op.year <= 2100):
                return err('运作日期超出合理范围（2000–2100）')
            if new_op != rec.operation_date:
                rec.operation_date = new_op
                rec.due_date = rec._compute_due_date()
        for field in ('estimated_amount',):
            if field in data:
                setattr(rec, field, _dec(data[field]))
        if 'actual_invoice_amount' in data:
            rec.actual_invoice_amount = _dec(data['actual_invoice_amount']) if data['actual_invoice_amount'] not in (None, '') else None
        if 'account_diff_adjustment' in data:
            # 兼容旧调用方按「合计」编辑：与现合计的差值生成一条调整明细，
            # 明细为正源、合计为派生（与运作年月→日期同款的派生列策略）
            new_total = _dec(data['account_diff_adjustment'])
            delta = new_total - (rec.account_diff_adjustment or Decimal('0'))
            if delta:
                from paikuan.models import PaikuanUser as _PU
                ARAdjustment.objects.create(
                    ar_record=rec, amount=delta,
                    reason=(data.get('adjustment_reason') or '').strip() or '人工调整（按合计修改）',
                    created_by=_PU.objects.filter(id=request.pk_uid).first())
                rec.account_diff_adjustment = new_total
        if 'tax_amount' in data:
            rec.tax_amount = _dec(data['tax_amount']) if data['tax_amount'] not in (None, '') else None
        if 'invoice_date' in data:
            rec.invoice_date = _normalize_date(data['invoice_date']) or None
        if 'reconciliation_date' in data:
            rec.reconciliation_date = _normalize_date(data['reconciliation_date']) or None
        if 'target_collection_date' in data:
            rec.target_collection_date = _normalize_date(data['target_collection_date']) or None
        if 'invoice_batch_no' in data:
            rec.invoice_batch_no = (data['invoice_batch_no'] or '').strip()
        if 'notes' in data:
            rec.notes = data['notes'].strip()
        # 触碰了开票字段时校验配套关系（不触碰则不追溯存量数据，避免改备注也被拦）
        if (('actual_invoice_amount' in data or 'invoice_date' in data)
                and rec.actual_invoice_amount is not None and not rec.invoice_date):
            return err('已填实际开票金额，请同时填写开票日期')
        try:
            rec.save()
        except Exception as e:
            return err(str(e))
        return ok(apply_ar_view_mask(
            rec.to_dict(today=today, include_payments=True),
            get_request_perms(request), 'record'))

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        rec.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_record_template(request):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '应收账款明细'
    headers = ['项目编号', '项目简称*', '交付部门', '客户名称', '运作日期*', '预估上账金额', '实际开票金额',
               '税额(差额模式手填)', '开票日期', '账实差额调整', '差额原因', '目标回款日期', '回款金额', '回款时间', '备注']
    _header_row(ws, headers, color='1B6E35')
    tip_vals = [
        '选填：项目编号（如 YS-20260101-0001）。当同名项目有多个时，填此列可精确指定，避免歧义',
        '★必填：填写项目台账中的"项目简称"（找不到将拒绝导入并提示先建项目；同名多个时需填交付部门/编号区分）',
        '选填：交付部门/事业部。当不同事业部存在同名项目时，填此列即可精确区分（推荐）',
        '选填：客户名称，用于区分同名项目（同部门同名时再用此列）',
        '★必填：应收发生日期，格式 2026-05-01 / 2026/5/1 均可；只填到月（如 2026-05）按当月1日处理。'
        '旧模板的「运作年」「运作月」两列仍兼容',
        '选填：当月预计上账金额（元）；计算公式：未回款 = 上账金额 + 账实差额调整 - 全部回款之和',
        '选填：实际开票金额（元）；全额模式下税额自动计算；对账时以此确认是否已对账',
        '选填：差额模式时手动填写税额（元）；全额模式：税额=开票金额÷(1+税率)×税率，自动算，无需填',
        '选填：格式 2026-01-15 / 2026/1/15 / 2026年1月15日 均可',
        '选填：账实差额调整（元，可正可负）；未回款 = 上账金额 + 此值 - 已回款；导入后生成一条调整明细，后续可在记录上多次追加不同原因的调整',
        '选填：本次差额的原因（如：运费差/客户扣款/补付/四舍五入），留空记为"导入差额调整"',
        '选填：目标回款日期（业务手工设定的回款目标），格式 2026-02-15；与系统按账期推算的「应收日期」并行',
        '选填：本次回款金额（元）；同一明细行可有多次回款，每次导入新回款均追加，不覆盖历史',
        '选填：回款日期，格式同上（月度回款率按回款日期所在月份计算）',
        '选填备注',
    ]
    ws.append(tip_vals)
    tip_row = ws.max_row
    tip_fill = PatternFill('solid', fgColor='E8F5E9')
    tip_font = Font(italic=True, color='1B5E20', size=9)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(tip_row, c)
        cell.fill = tip_fill
        cell.font = tip_font
        cell.alignment = Alignment(wrap_text=True)
    ws.row_dimensions[tip_row].height = 60
    ws.append(['', EXAMPLE_ROW_MARKER, '运输事业部', '', '2026-01-05', 100000, 100000, '', '2026-01-15', 0,
               '', '2026-02-15', 30000, '2026-01-20', '示例（此行含"示例"标记，导入时自动跳过）'])
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 22
    return _export_response(wb, '应收账款明细导入模板.xlsx')


_AR_RECORD_AI_SYS = (
    '你是企业应收账款的数据质检助手。下面是一批待导入的应收明细记录（已通过基础格式校验）。'
    '请只挑出"疑似有问题"的行：项目简称像占位符/测试数据；预估上账金额或实际开票金额异常'
    '（0元/极大极小/疑似少零）；开票日期晚于回款日期；疑似重复行；回款金额超过上账金额。'
    '严格只返回 JSON 数组，每个元素形如 '
    '{"row":行号,"field":"字段名","issue":"问题简述","suggestion":"修正建议(可空)","severity":"high|medium|low"}。'
    '没有发现问题就返回 []。不要输出 JSON 以外的任何文字。'
)

_AR_RECORD_COLUMNS = [
    {'key': 'short_name', 'label': '项目简称'},
    {'key': 'dept_hint', 'label': '交付部门'},
    {'key': 'op_date', 'label': '运作日期'},
    {'key': 'est', 'label': '预估上账金额'},
    {'key': 'actual', 'label': '实际开票金额'},
    {'key': 'inv_date', 'label': '开票日期'},
    {'key': 'notes', 'label': '备注', 'wide': True},
]


@csrf_exempt
@pk_required()
def ar_record_import_precheck(request):
    """应收明细导入预检：格式校验 + 项目存在性检查 + AI 复核。只读不落库。
    用户确认后由前端重新提交文件到 /import 写库（AR 通用「文件留存+重提」模式）。"""
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _page_denied(request, 'ar_records')
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
    except Exception as e:
        return err(f'无法读取Excel: {e}')

    data_rows = ws.max_row - 1
    if data_rows > PRECHECK_MAX:
        return ok({'skipPrecheck': True, 'total': data_rows,
                   'reason': f'数据量较大（约 {data_rows} 行），已跳过 AI 预检，直接导入。'})

    headers = [str(ws.cell(1, c).value or '').strip() for c in range(1, ws.max_column + 1)]
    col_map = {_norm_header(h): i + 1 for i, h in enumerate(headers)}
    _ALIASES = {
        '项目简称*':         ['项目简称*', '项目简称'],
        '交付部门':          ['交付部门', '事业部', '部门'],
        '运作日期*':         ['运作日期*', '运作日期'],
        '运作年*':           ['运作年*', '运作年'],
        '运作月*':           ['运作月*', '运作月'],
        '预估上账金额':      ['预估上账金额', '预估金额', '上账金额'],
        '实际开票金额':      ['实际开票金额', '开票金额'],
        '开票日期':          ['开票日期', '开票日期(YYYY-MM-DD)', '开票日期*'],
        '回款金额':          ['回款金额'],
        '回款时间':          ['回款时间', '回款时间(YYYY-MM-DD)', '回款日期'],
        '备注':              ['备注'],
    }

    def _resolve_idx(name):
        for h in _ALIASES.get(name, [name]):
            if _norm_header(h) in col_map:
                return col_map[_norm_header(h)]
        return None

    def _cv_raw(row, name):
        idx = _resolve_idx(name)
        return ws.cell(row, idx).value if idx else None

    def _cv(row, name):
        v = _cv_raw(row, name)
        return str(v).strip() if v is not None else ''

    DATA_COLS = ('项目简称*', '交付部门', '运作日期*', '运作年*', '运作月*',
                 '预估上账金额', '实际开票金额', '开票日期', '回款金额', '回款时间', '备注')

    allowed_depts = None if request.pk_role == 'super_admin' else request.pk_depts
    report_rows, ai_input = [], []

    for ri in range(2, ws.max_row + 1):
        row_vals = {h: _cv(ri, h) for h in DATA_COLS}
        short_name = row_vals['项目简称*']
        has_any = any(v for v in row_vals.values())
        if EXAMPLE_ROW_MARKER in short_name or short_name.startswith('★'):
            continue
        if not has_any:
            continue
        rule_issue = None
        if not short_name:
            rule_issue = '缺少「项目简称」，请补填'
        else:
            dept_hint = row_vals['交付部门']
            if dept_hint and dept_hint not in VALID_DEPARTMENTS:
                rule_issue = f'交付部门"{dept_hint}"无效，可选值为：{"/".join(VALID_DEPARTMENTS)}'
            if not rule_issue:
                status, payload = _classify_project_for_import(
                    short_name, '', '', allowed_depts, dept_hint=dept_hint)
                if status == 'not_found':
                    rule_issue = f'项目「{short_name}」在项目台账中不存在，请先在台账新建'
                elif status == 'ambiguous':
                    depts = sorted({c['delivery_dept'] for c in payload if c.get('delivery_dept')})
                    rule_issue = (f'项目「{short_name}」匹配到 {len(payload)} 个，无法区分'
                                  + (f'（部门：{"/".join(depts)}，请填交付部门区分）' if len(depts) > 1 else ''))
                elif status == 'bad_no':
                    rule_issue = '项目编号无效，请清空后改用简称匹配'
            if not rule_issue:
                od_raw = _cv_raw(ri, '运作日期*')
                if od_raw not in (None, ''):
                    od_norm = _normalize_date(od_raw)
                    if not od_norm:
                        m = re.match(r'^\s*(\d{4})\s*[-/年.]\s*(\d{1,2})\s*月?\s*$', str(od_raw))
                        if not m:
                            rule_issue = f'「运作日期」"{od_raw}"格式无效，请用 2026-05-01 格式'
                else:
                    if not (row_vals['运作年*'] or row_vals['运作月*']):
                        rule_issue = '缺少「运作日期」，请补填（如 2026-05-01）'
            if not rule_issue:
                for amt_col, lbl in (('预估上账金额', '预估上账金额'), ('实际开票金额', '实际开票金额'),
                                     ('回款金额', '回款金额')):
                    raw = row_vals[amt_col]
                    if raw:
                        try:
                            Decimal(str(raw).replace(',', '').replace('，', ''))
                        except Exception:
                            rule_issue = f'「{lbl}」"{raw}"不是有效数字'; break

        dept_hint = row_vals['交付部门']
        op_date_str = str(_cv_raw(ri, '运作日期*') or '').strip() or f"{row_vals['运作年*']}-{row_vals['运作月*']}"
        data = {'short_name': short_name, 'dept_hint': dept_hint, 'op_date': op_date_str,
                'est': row_vals['预估上账金额'], 'actual': row_vals['实际开票金额'],
                'inv_date': _cv(ri, '开票日期'), 'notes': row_vals['备注']}
        report_rows.append({'row': ri, 'data': data, 'ruleIssue': rule_issue, 'warn': None, 'ai': []})
        if not rule_issue:
            ai_input.append({'row': ri, 'short_name': short_name, 'dept': dept_hint,
                             'op_date': op_date_str, 'est': row_vals['预估上账金额'],
                             'actual': row_vals['实际开票金额']})

    by_row = {}
    for fnd in _ar_ai_review(ai_input, _AR_RECORD_AI_SYS):
        by_row.setdefault(fnd['row'], []).append(fnd)
    for rr in report_rows:
        rr['ai'] = by_row.get(rr['row'], [])

    return ok(_ar_precheck_report(report_rows, _AR_RECORD_COLUMNS))


@csrf_exempt
@pk_required()
def ar_record_import(request):
    """应收明细批量导入。

    设计原则：
    - 格式错误（年月/金额/日期非法）→ 整表拒绝，列出全部问题
    - 项目找不到 → 自动创建草稿项目（不阻断导入）
    - 模糊匹配 / 多候选 → 取最新项目并在返回摘要里说明，请人工核查
    - 成功后返回三段式摘要：精确匹配 / 模糊匹配 / 自动新建
    """
    denied = _page_denied(request, 'ar_records')
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
    try:
        wb = openpyxl.load_workbook(f, data_only=True)
        ws = wb.active
    except Exception as e:
        return err(f'无法读取Excel: {e}')

    headers = [str(ws.cell(1, c).value or '').strip() for c in range(1, ws.max_column + 1)]
    # 规范化表头（去 *、括号注释），与 project_import 保持一致，使带备注的表头也能匹配
    col_map = {_norm_header(h): i + 1 for i, h in enumerate(headers)}

    _ALIASES = {
        '项目编号':          ['项目编号', '项目编号(可选,精确指定)', '项目编号*'],
        '项目简称*':         ['项目简称*', '项目简称'],
        '交付部门':          ['交付部门', '事业部', '部门'],
        '客户名称':          ['客户名称', '客户', '合同名称'],
        '运作日期*':         ['运作日期*', '运作日期'],
        '运作年*':           ['运作年*', '运作年'],
        '运作月*':           ['运作月*', '运作月'],
        '预估上账金额':      ['预估上账金额', '预估金额', '上账金额'],
        '实际开票金额':      ['实际开票金额', '开票金额'],
        '税额(差额模式手填)':['税额(差额模式手填)', '税额'],
        '开票日期':          ['开票日期', '开票日期(YYYY-MM-DD)', '开票日期*'],
        '账实差额调整':      ['账实差额调整', '账实差额'],
        '差额原因':          ['差额原因', '差额调整原因', '调整原因'],
        '目标回款日期':      ['目标回款日期', '目标回款', '目标回款日'],
        '回款金额':          ['回款金额'],
        '回款时间':          ['回款时间', '回款时间(YYYY-MM-DD)', '回款日期'],
        '备注':              ['备注'],
    }

    def _resolve_idx(name):
        for h in _ALIASES.get(name, [name]):
            if _norm_header(h) in col_map:
                return col_map[_norm_header(h)]
        return None

    def _cv_raw(row, name):
        idx = _resolve_idx(name)
        return ws.cell(row, idx).value if idx else None

    def _cv(row, name):
        v = _cv_raw(row, name)
        return str(v).strip() if v is not None else ''

    def _num_or_err(raw, label, ri):
        if raw is None or str(raw).strip() == '':
            return None, None
        s = str(raw).strip().replace(',', '').replace('，', '')
        try:
            return Decimal(s), None
        except (InvalidOperation, TypeError):
            return None, (f'第{ri}行：「{label}」填的是"{raw}"，不是有效数字。'
                          f'请填纯数字（如 12000，不要带逗号、空格、"元""万"等单位）')

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    allowed_depts = None if request.pk_role == 'super_admin' else request.pk_depts

    DATA_COLS = ('项目编号', '项目简称*', '交付部门', '客户名称', '运作日期*', '运作年*', '运作月*',
                 '预估上账金额', '实际开票金额', '税额(差额模式手填)', '开票日期', '账实差额调整',
                 '差额原因', '目标回款日期', '回款金额', '回款时间', '备注')

    errors = []      # 格式错误：会导致整表拒绝
    skipped = 0      # 仅保留字段兼容（恒为0）：示例/空行静默忽略，不计入
    plan = []        # 通过格式校验的行，待写入

    # ══ 阶段一：格式校验（不写库，不查项目）══════════════════════════════════
    for ri in range(2, ws.max_row + 1):
        row_vals = {h: _cv(ri, h) for h in DATA_COLS}
        short_name = row_vals['项目简称*']
        has_any = any(v for v in row_vals.values())

        # 示例/提示行、整行空白：静默忽略（不计入、不报错）
        if EXAMPLE_ROW_MARKER in short_name or short_name.startswith('★'):
            continue
        if not has_any:
            continue
        if not short_name:
            errors.append(f'第{ri}行：缺少「项目简称」，请补填（项目简称是关联应收记录与项目的唯一桥梁）')
            continue

        dept_hint = row_vals['交付部门']
        if dept_hint and dept_hint not in VALID_DEPARTMENTS:
            errors.append(f'第{ri}行：交付部门"{dept_hint}"无效，可选值为：{"/".join(VALID_DEPARTMENTS)}（留空则按项目简称匹配）')
            continue

        # 运作日期（正源）：新模板单列日期；旧模板「运作年+运作月」仍兼容（按当月1日）
        op_date = None
        od_raw = _cv_raw(ri, '运作日期*')
        if od_raw not in (None, ''):
            od_norm = _normalize_date(od_raw)
            try:
                op_date = datetime.date.fromisoformat(od_norm) if od_norm else None
            except ValueError:
                op_date = None
            if op_date is None:
                # 只填到月（2026-05 / 2026/5 / 2026年5月）→ 当月1日
                m = re.match(r'^\s*(\d{4})\s*[-/年.]\s*(\d{1,2})\s*月?\s*$', str(od_raw))
                if m and 1 <= int(m.group(2)) <= 12:
                    op_date = datetime.date(int(m.group(1)), int(m.group(2)), 1)
            if op_date is None:
                errors.append(f'第{ri}行：「运作日期」"{od_raw}"格式无效，'
                              f'请用 2026-05-01（或只填到月 2026-05，按当月1日处理）')
                continue
        else:
            y_raw, m_raw = row_vals['运作年*'], row_vals['运作月*']
            if not (y_raw or m_raw):
                errors.append(f'第{ri}行：缺少「运作日期」（如 2026-05-01）。'
                              f'旧模板可继续填「运作年」「运作月」两列，按当月1日处理')
                continue
            try:
                year, month = int(float(y_raw or 0)), int(float(m_raw or 0))
            except (ValueError, TypeError):
                errors.append(f'第{ri}行：运作年/月必须是数字（当前 年="{y_raw}" 月="{m_raw}"）')
                continue
            if not (2000 <= year <= 2100 and 1 <= month <= 12):
                errors.append(f'第{ri}行：运作年/月无效（年="{y_raw}" 月="{m_raw}"）。'
                              f'运作年需为四位年份（如 2026），运作月需为 1-12')
                continue
            op_date = datetime.date(year, month, 1)
        if not (2000 <= op_date.year <= 2100):
            errors.append(f'第{ri}行：运作日期 {op_date} 超出合理范围（2000–2100）')
            continue

        est, e = _num_or_err(row_vals['预估上账金额'], '预估上账金额', ri)
        if e: errors.append(e); continue
        actual, e = _num_or_err(row_vals['实际开票金额'], '实际开票金额', ri)
        if e: errors.append(e); continue
        tax, e = _num_or_err(row_vals['税额(差额模式手填)'], '税额', ri)
        if e: errors.append(e); continue
        diff, e = _num_or_err(row_vals['账实差额调整'], '账实差额调整', ri)
        if e: errors.append(e); continue
        pay_amount, e = _num_or_err(row_vals['回款金额'], '回款金额', ri)
        if e: errors.append(e); continue

        inv_raw = _cv_raw(ri, '开票日期')
        inv_date = _normalize_date(inv_raw)
        if inv_raw not in (None, '') and inv_date is None:
            errors.append(f'第{ri}行：「开票日期」"{inv_raw}"格式无效，请用 2026-01-15 格式')
            continue
        tgt_raw = _cv_raw(ri, '目标回款日期')
        tgt_date = _normalize_date(tgt_raw)
        if tgt_raw not in (None, '') and tgt_date is None:
            errors.append(f'第{ri}行：「目标回款日期」"{tgt_raw}"格式无效，请用 2026-02-15 格式（选填，可留空）')
            continue
        pay_raw = _cv_raw(ri, '回款时间')
        pay_date = _normalize_date(pay_raw)
        if pay_raw not in (None, '') and pay_date is None:
            errors.append(f'第{ri}行：「回款时间」"{pay_raw}"格式无效，请用 2026-01-20 格式')
            continue
        if pay_amount and pay_amount > 0 and not pay_date:
            errors.append(f'第{ri}行：填了「回款金额」却没填「回款时间」，请补填或清空回款金额')
            continue
        if pay_date and not (pay_amount and pay_amount > 0):
            errors.append(f'第{ri}行：填了「回款时间」却没填有效「回款金额」，请补填或清空回款时间')
            continue

        # 超收检查：回款金额 > 预估上账+账实差额 → 未收余额将为负，整表拒绝并给出指引
        if pay_amount and pay_amount > Decimal('0'):
            pay_base = (est or Decimal('0')) + (diff or Decimal('0'))
            if pay_amount > pay_base:
                outstanding_after = pay_base - pay_amount
                errors.append(
                    f'第{ri}行（{short_name}）：回款金额 {pay_amount} 元'
                    f' > 预估上账{(" + 账实差额调整" if diff else "")} {pay_base} 元，'
                    f'未收余额将为 {outstanding_after:.2f} 元（负数），导入被拒绝。\n'
                    f'    ① 核查金额是否有误，修正后重新导入\n'
                    f'    ② 先不填回款列，导入明细后再在「录入回款」里手动补录\n'
                    f'    ③ 如有账实差额，在「账实差额调整」列填 {(pay_amount - pay_base):.2f}'
                    f'，使未收归零'
                )
                continue

        plan.append({
            'ri': ri, 'short_name': short_name,
            'project_no': row_vals['项目编号'],
            'dept_hint': dept_hint,
            'customer_hint': row_vals['客户名称'],
            'op_date': op_date,
            'est': est, 'actual': actual, 'tax': tax, 'inv_date': inv_date,
            'diff': diff, 'diff_reason': (row_vals['差额原因'] or '').strip(),
            'notes': row_vals['备注'], 'tgt_date': tgt_date,
            'pay_amount': pay_amount, 'pay_date': pay_date,
        })

    # ── 任何格式错误 → 整表拒绝 ──────────────────────────────────────────────
    if errors:
        return ok({
            'rejected': True, 'created': 0, 'skipped': skipped, 'errors': errors,
            'message': (f'导入未执行：发现 {len(errors)} 处格式问题，已全部列出。'
                        f'请按提示修正后重新导入（整表全部通过才会写入）。'),
        })

    # ══ 阶段一·补：项目归属检查（只读，不写库）══════════════════════════════
    # 多个同名项目无法区分、项目编号填了却查不到、或项目在台账中不存在 → 整表拒绝
    # 并给出可选项/指导。（已停用「自动建草稿」：找不到的项目要求先在台账建好。）
    ambiguities = []   # [{ri, input, candidates}]
    bad_nos = []       # [{ri, input, project_no}]
    not_founds = []    # [{ri, input}] 台账中不存在的项目
    for p in plan:
        status, payload = _classify_project_for_import(
            p['short_name'], p['customer_hint'], p['project_no'], allowed_depts,
            dept_hint=p['dept_hint'])
        if status == 'ambiguous':
            ambiguities.append({'ri': p['ri'], 'input': p['short_name'], 'candidates': payload})
        elif status == 'bad_no':
            bad_nos.append({'ri': p['ri'], 'input': p['short_name'], 'project_no': payload})
        elif status == 'not_found':
            not_founds.append({'ri': p['ri'], 'input': p['short_name']})

    if ambiguities or bad_nos or not_founds:
        guide = []
        for b in bad_nos:
            guide.append(f'第{b["ri"]}行：填写的「项目编号」{b["project_no"]} 不存在或不在您的权限范围内，'
                         f'请核对编号，或清空编号改用「项目简称」匹配。')
        for nf in not_founds:
            guide.append(f'第{nf["ri"]}行：项目「{nf["input"]}」在项目台账中不存在（或不在您的权限部门内）。'
                         f'请先到「项目台账」新建该项目，再导入其应收明细。')
        for a in ambiguities:
            depts = sorted({c['delivery_dept'] for c in a['candidates'] if c.get('delivery_dept')})
            tip = ('（这几个项目同名但分属不同事业部，填「交付部门」即可区分）'
                   if len(depts) > 1 else '')
            lines = [f'第{a["ri"]}行：「{a["input"]}」匹配到 {len(a["candidates"])} 个项目，无法确定是哪一个。'
                     f'请在导入表填「交付部门」列区分{tip}，或填「项目编号」精确指定；同名同部门时再用「客户名称」区分：']
            for c in a['candidates']:
                lines.append(f'    · 编号 {c["project_no"]}｜简称 {c["short_name"]}'
                             f'｜部门 {c["delivery_dept"]}｜客户 {c["customer_name"] or "—"}')
            guide.append('\n'.join(lines))
        parts = []
        if not_founds:
            parts.append(f'{len(not_founds)} 处项目不存在')
        if ambiguities:
            parts.append(f'{len(ambiguities)} 处项目无法唯一确定')
        if bad_nos:
            parts.append(f'{len(bad_nos)} 处项目编号无效')
        return ok({
            'rejected': True, 'created': 0, 'skipped': skipped,
            'errors': guide, 'ambiguities': ambiguities, 'bad_nos': bad_nos, 'not_founds': not_founds,
            'message': (f'导入未执行：{"、".join(parts)}。'
                        f'请按下方指引先在项目台账补建项目 / 补「项目编号」「客户名称」后重新导入。'),
        })

    # ══ 阶段二：项目匹配 + 写入（事务）══════════════════════════════════════
    # 说明：应收明细导入为【纯增量】——每个计划行写入一条独立 ARRecord，
    # 绝不按客户/合同/简称做合并或去重（同项目同月多条属正常多笔）。
    # proj_cache 防止同一批次重复创建同名草稿
    proj_cache = {}
    # 按 match_type 收集摘要
    match_buckets = {'exact': {}, 'exact_multi': {}, 'fuzzy': {}, 'fuzzy_multi': {}, 'created': {}}

    created = 0
    pay_warnings = []          # 回款超额行（阶段一已拦截，此处仅作双重保险记录）
    reject_errors = []         # 阶段二兜底：项目不存在/越权（停用草稿后整表回滚）
    with transaction.atomic():
        for p in plan:
            proj, match_type, warn = _resolve_project_for_import(
                p['short_name'], p['customer_hint'], p['dept_hint'], allowed_depts, user, proj_cache,
                project_no=p['project_no'])

            # 已停用「自动建草稿」：项目不存在 / 解析为新建 / 越权 → 收集错误，整表回滚
            if (proj is None or match_type == 'created'
                    or (request.pk_role != 'super_admin'
                        and proj.delivery_dept not in request.pk_depts)):
                reject_errors.append(
                    f'第{p["ri"]}行：项目「{p["short_name"]}」在项目台账中不存在或不在您的权限部门内，'
                    f'请先到「项目台账」新建该项目后再导入应收。')
                continue

            # 记录到摘要 bucket
            key = proj.short_name
            bucket = match_buckets.setdefault(match_type, {})
            if key not in bucket:
                bucket[key] = {
                    'short_name': proj.short_name,
                    'customer_name': proj.customer_name,
                    'project_id': proj.id,
                    'is_draft': proj.is_draft,
                    'matched_to': proj.short_name,
                    'input': p['short_name'],
                    'count': 0,
                    'warn': warn,
                }
            bucket[key]['count'] += 1

            rec = ARRecord(project=proj, operation_date=p['op_date'], created_by=user)
            if p['est'] is not None and _can_ar_view(request, 'r_estimated_amount'):
                rec.estimated_amount = p['est']
            if _can_ar_view(request, 'r_actual_invoice_amount'):
                rec.actual_invoice_amount = p['actual']
            if _can_ar_view(request, 'r_tax_amount'):
                rec.tax_amount = p['tax']
            if _can_ar_view(request, 'r_invoice_date'):
                rec.invoice_date = p['inv_date']
            if p['tgt_date'] and _can_ar_view(request, 'r_due_date'):
                rec.target_collection_date = p['tgt_date']
            if _can_ar_view(request, 'r_notes'):
                rec.notes = p['notes']
            rec.save()
            # 差额走调整明细（合计由信号派生）；须在回款写入前生效，
            # 否则回款校验「未收不为负」时差额还没计入
            if p['diff'] and _can_ar_view(request, 'r_account_diff'):
                ARAdjustment.objects.create(
                    ar_record=rec, amount=p['diff'],
                    reason=p['diff_reason'][:200] or '导入差额调整', created_by=user)
            if p['pay_amount'] and p['pay_date']:
                ARPayment.objects.create(ar_record=rec, payment_no=1,
                                         amount=p['pay_amount'], payment_date=p['pay_date'],
                                         notes='导入回款')
            created += 1
        if reject_errors:
            transaction.set_rollback(True)

    if reject_errors:
        return ok({
            'rejected': True, 'created': 0, 'skipped': skipped, 'errors': reject_errors,
            'message': ('导入未执行：存在项目台账中不存在的项目，'
                        '请先在「项目台账」建好项目再重导（系统已停用导入自动建草稿）。'),
        })

    # ── 汇总输出 ──────────────────────────────────────────────────────────────
    def _bucket_list(btype):
        # 行级写入失败会把 count 减回，过滤掉 count<=0 的空壳，避免摘要里出现 0 条项
        return [v for v in match_buckets.get(btype, {}).values() if v['count'] > 0]

    draft_count = len(_bucket_list('created'))
    match_detail = {
        'exact':       _bucket_list('exact'),
        'exact_multi': _bucket_list('exact_multi'),
        'fuzzy':       _bucket_list('fuzzy'),
        'fuzzy_multi': _bucket_list('fuzzy_multi'),
        'created':     _bucket_list('created'),
    }
    warnings = []
    for btype in ('exact_multi', 'fuzzy', 'fuzzy_multi', 'created'):
        for item in match_detail[btype]:
            if item.get('warn'):
                warnings.append(f'【{item["short_name"]}】{item["warn"]}')
    warnings.extend(pay_warnings)   # 回款超额警告优先展示

    tip = '导入后系统已按现规则自动重算未收回金额。'
    if draft_count:
        tip += f' 有 {draft_count} 个草稿项目需到「项目台账」补充完善。'

    return ok({
        'created': created, 'skipped': skipped, 'errors': [],
        'match_detail': match_detail,
        'warnings': warnings,
        'has_draft_projects': draft_count > 0,
        'draft_count': draft_count,
        'tip': tip,
    })


@csrf_exempt
@pk_required()
def ar_record_export(request):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    today = datetime.date.today()
    # 导出与列表口径一致：复用同一套筛选 + 条件构建器（含日期相对区间/金额运算符）
    qs = _ar_dept_filter(ARRecord.objects.select_related('project'), request,
                         shared_field='project__is_shared')
    qs = _apply_record_filters(qs, request)
    qs = _apply_record_state_filters(qs, request, today)
    qs = _apply_conditions(qs, request, today)
    qs = _apply_record_sort(qs, request)
    # 列头筛选 + 列头排序：与列表口径一致
    qs = _apply_colfilter_sort(qs, request)
    if qs.count() > 5000:
        return err('导出超过5000行，请缩小筛选范围')
    qs = qs.prefetch_related('payments')

    def _pay_dates(rec):
        return ' / '.join(str(p.payment_date) for p in rec.payments.all())

    def _pay_amounts(rec):
        return ' / '.join(f'{float(p.amount):.2f}' for p in rec.payments.all())

    def _pay_total(rec):
        s = sum((p.amount for p in rec.payments.all()), Decimal('0'))
        return float(s) if s else 0.0

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '应收账款明细'
    columns = _visible_ar_export_cols(request, [
        (None, '项目编号', lambda rec, st: rec.project.project_no),
        ('p_short_name', '项目简称', lambda rec, st: rec.project.short_name),
        ('p_contract_name', '客户名称', lambda rec, st: rec.project.customer_name),
        ('p_delivery_dept', '交付部门', lambda rec, st: rec.delivery_dept),
        ('p_project_manager', '项目负责人', lambda rec, st: rec.project.project_manager),
        ('p_sales_contact', '销售对接人', lambda rec, st: rec.project.sales_contact),
        ('p_account_period', '总账期(天)', lambda rec, st: rec.project.total_days),
        (None, '运作日期', lambda rec, st: str(rec.operation_date) if rec.operation_date else ''),
        ('r_estimated_amount', '预估上账金额', lambda rec, st: float(rec.estimated_amount)),
        ('r_actual_invoice_amount', '实际开票金额',
         lambda rec, st: float(rec.actual_invoice_amount) if rec.actual_invoice_amount is not None else ''),
        ('r_tax_amount', '税额', lambda rec, st: float(rec.tax_amount) if rec.tax_amount is not None else ''),
        ('r_invoice_date', '开票日期', lambda rec, st: str(rec.invoice_date) if rec.invoice_date else ''),
        ('p_invoice_config', '开票模式', lambda rec, st: rec.project.invoice_mode),
        ('r_account_diff', '账实差额调整', lambda rec, st: float(rec.account_diff_adjustment)),
        ('r_account_diff', '差额明细',
         lambda rec, st: '；'.join(f'{a.reason or "未填原因"}:{a.amount}'
                                   for a in rec.adjustments.all())),
        ('r_outstanding', '未回款金额', lambda rec, st: float(rec.outstanding_amount)),
        # 回款明细：同一明细可有多笔回款，日期/金额按 " / " 并列，另给已回款合计
        ('r_payments', '回款日期', lambda rec, st: _pay_dates(rec)),
        ('r_payments', '回款金额', lambda rec, st: _pay_amounts(rec)),
        ('r_payments', '已回款合计', lambda rec, st: _pay_total(rec)),
        ('r_payments', '预收冲抵金额',
         lambda rec, st: float(sum(p.amount for p in rec.payments.all()
                                   if p.source == '预收抵扣')) or ''),
        ('r_payments', '预收冲抵次数',
         lambda rec, st: sum(1 for p in rec.payments.all() if p.source == '预收抵扣') or ''),
        ('r_payments', '内部往来金额',
         lambda rec, st: float(sum(p.amount for p in rec.payments.all()
                                   if p.source == '内部往来')) or ''),
        ('r_payments', '内部往来次数',
         lambda rec, st: sum(1 for p in rec.payments.all() if p.source == '内部往来') or ''),
        ('r_due_date', '应收日期', lambda rec, st: str(rec.due_date) if rec.due_date else ''),
        ('r_due_date', '目标回款日期',
         lambda rec, st: str(rec.target_collection_date) if rec.target_collection_date else ''),
        ('r_reconciliation', '对账状态', lambda rec, st: rec.reconciliation_status),
        ('r_reconciliation', '对账日期',
         lambda rec, st: rec.reconciliation_date.strftime('%Y-%m-%d') if rec.reconciliation_date else ''),
        ('r_invoice_status', '开票状态', lambda rec, st: rec.invoice_status),
        ('r_due_date', '是否逾期', lambda rec, st: '是' if st['is_overdue'] else ''),
        ('r_due_date', '逾期天数', lambda rec, st: st['overdue_days'] if st['is_overdue'] else ''),
        ('r_notes', '备注', lambda rec, st: rec.notes),
    ])
    _header_row(ws, [header for _, header, _ in columns], color='1B6E35')
    for rec in qs:
        st = rec.status_dict(today)
        ws.append([getter(rec, st) for _, _, getter in columns])
    return _export_response(wb, '应收账款明细.xlsx')




@csrf_exempt
@pk_required()
def ar_records_kpi(request):
    """Per-tracking completion KPIs for the current filter (对账/开票/回款)."""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    today = datetime.date.today()
    qs = _apply_record_filters(
        _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared'), request)
    qs = _apply_conditions(qs, request, today)

    total = qs.count()

    # Reconciliation: 已对账 vs 未对账
    recon_done = qs.filter(Q(reconciliation_date__isnull=False) | Q(actual_invoice_amount__isnull=False)).count()
    recon_pending = total - recon_done

    # Invoice: 已开票 vs 未开票（含金额）。已结清记录不计入「待开票」，与
    # invoice_status 属性及列表筛选保持一致（已结清优先级高于未开票）。
    inv_done_qs = qs.filter(actual_invoice_amount__isnull=False)
    inv_done = inv_done_qs.count()
    inv_pending_qs = qs.filter(actual_invoice_amount__isnull=True, outstanding_amount__gt=0)
    inv_pending = inv_pending_qs.count()
    # 未开票预估金额：尚未开票且仍有未收余额记录的预估上账金额合计
    inv_pending_amount = inv_pending_qs.aggregate(s=Sum('estimated_amount'))['s'] or 0
    inv_done_amount = inv_done_qs.aggregate(s=Sum('actual_invoice_amount'))['s'] or 0

    # Collection: 已结清 vs 未收
    settled = qs.filter(outstanding_amount__lte=0).count()
    outstanding_qs = qs.filter(outstanding_amount__gt=0)
    outstanding_count = outstanding_qs.count()
    outstanding_amount = outstanding_qs.aggregate(s=Sum('outstanding_amount'))['s'] or 0
    # 已收总额（当前筛选集所有回款之和）
    collected_amount = qs.aggregate(s=Sum('payments__amount'))['s'] or 0
    estimated_total = qs.aggregate(s=Sum('estimated_amount'))['s'] or 0

    # Overdue (within current filter)
    overdue_qs = qs.filter(outstanding_amount__gt=0, due_date__lt=today)
    overdue_count = overdue_qs.count()
    overdue_amount = overdue_qs.aggregate(s=Sum('outstanding_amount'))['s'] or 0

    def _rate(done, tot):
        return round(done / tot * 100, 1) if tot else 100.0

    return ok({
        'total': total,
        'estimated_total': str(estimated_total),
        'reconciliation': {
            'done': recon_done, 'pending': recon_pending,
            'rate': _rate(recon_done, total),
            'pending_amount': str(qs.filter(reconciliation_date__isnull=True, actual_invoice_amount__isnull=True)
                                  .aggregate(s=Sum('outstanding_amount'))['s'] or 0),
        },
        'invoice': {
            'done': inv_done, 'pending': inv_pending,
            'rate': _rate(inv_done, total),
            'pending_amount': str(inv_pending_amount),
            'done_amount': str(inv_done_amount),
        },
        'collection': {
            'settled': settled,
            'outstanding_count': outstanding_count,
            'outstanding_amount': str(outstanding_amount),
            'collected_amount': str(collected_amount),
            'rate': _rate(settled, total),
        },
        'overdue': {'count': overdue_count, 'amount': str(overdue_amount)},
    })


# ──────────────────────────────────────────────────────────────────────────────
# 回款流水 (payment ledger) — cross-record payments filtered by date range
# ──────────────────────────────────────────────────────────────────────────────

def _payment_ledger_qs(request):
    """Build the filtered ARPayment queryset for the ledger (shared by list+export)."""
    qs = (ARPayment.objects.select_related('ar_record', 'ar_record__project')
          .order_by('-payment_date', '-id'))
    qs = _ar_dept_filter(qs, request, dept_field='ar_record__delivery_dept',
                         shared_field='ar_record__project__is_shared')
    pay_start = request.GET.get('pay_start', '').strip()
    pay_end = request.GET.get('pay_end', '').strip()
    if pay_start:
        qs = qs.filter(payment_date__gte=pay_start)
    if pay_end:
        qs = qs.filter(payment_date__lte=pay_end)
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(ar_record__delivery_dept=dept)
    project_id = request.GET.get('project_id', '').strip()
    if project_id:
        qs = qs.filter(ar_record__project_id=int(project_id))
    source = request.GET.get('source', '').strip()
    if source:
        qs = qs.filter(source=source)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(ar_record__project__short_name__icontains=q) |
            Q(ar_record__project__customer_name__icontains=q) |
            Q(ar_record__project__project_no__icontains=q))
    return qs


def _payment_ledger_row(p):
    rec = p.ar_record
    proj = rec.project
    return {
        'id': p.id,
        'ar_record_id': rec.id,
        'payment_no': p.payment_no,
        'payment_date': str(p.payment_date) if p.payment_date else None,
        'amount': str(p.amount),
        'source': p.source,
        'counterparty_dept': p.counterparty_dept,
        'notes': p.notes,
        'project_no': proj.project_no,
        'short_name': proj.short_name,
        'delivery_dept': rec.delivery_dept,
        'operation_year': rec.operation_year,
        'operation_month': rec.operation_month,
        'operation_date': str(rec.operation_date) if rec.operation_date else None,
    }


@csrf_exempt
@pk_required()
def ar_payment_ledger(request):
    """跨记录回款流水：按回款日期区间 / 部门 / 项目 / 关键词筛选，并返回合计。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    denied = _ar_field_denied(request, 'r_payments')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)

    qs = _payment_ledger_qs(request)
    total = qs.count()
    total_amount = qs.aggregate(s=Sum('amount'))['s'] or 0
    page = max(1, int(request.GET.get('page', 1) or 1))
    size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
    rows = [_payment_ledger_row(p) for p in qs[(page - 1) * size: page * size]]
    return ok({
        'items': rows, 'total': total, 'page': page, 'size': size,
        'summary': {'count': total, 'total_amount': str(total_amount)},
    })


@csrf_exempt
@pk_required()
def ar_payment_ledger_export(request):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    denied = _ar_field_denied(request, 'r_payments')
    if denied:
        return denied
    qs = _payment_ledger_qs(request)
    if qs.count() > 5000:
        return err('导出超过5000行，请缩小筛选范围')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '回款流水'
    headers = ['回款日期', '回款金额', '来源', '往来部门', '项目编号', '项目简称',
               '交付部门', '运作年', '运作月', '回款序号', '备注']
    _header_row(ws, headers, color='1B6E35')
    for p in qs:
        r = _payment_ledger_row(p)
        ws.append([r['payment_date'], float(p.amount), r['source'], r['counterparty_dept'],
                   r['project_no'], r['short_name'], r['delivery_dept'],
                   r['operation_year'], r['operation_month'], r['payment_no'], r['notes']])
    return _export_response(wb, '回款流水.xlsx')


# ──────────────────────────────────────────────────────────────────────────────
# 多维汇总 (group-by pivot) — count + amount sums grouped by a chosen dimension
# ──────────────────────────────────────────────────────────────────────────────

_SUMMARY_GROUP_FIELDS = {
    'dept': ('delivery_dept', '交付部门'),
    'customer_level': ('project__customer_level', '客户等级'),
    'business_mode': ('project__business_mode', '业务模式'),
    'manager': ('project__project_manager', '项目负责人'),
    'month': ('operation_month', '运作年月'),
}

# 客户等级固定展示顺序：S → A → B → C → D，其余/未填写置后
_CUSTOMER_LEVEL_ORDER = {'S级': 0, 'A级': 1, 'B级': 2, 'C级': 3, 'D级': 4}


@csrf_exempt
@pk_required()
def ar_records_group_summary(request):
    """按指定维度对应收记录做计数 + 金额聚合（透视表）。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)

    today = datetime.date.today()
    qs = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
    qs = _apply_record_filters(qs, request)
    qs = _apply_record_state_filters(qs, request, today)
    qs = _apply_conditions(qs, request, today)
    # 若 flat 筛选带 payments JOIN（旧参数），落到无 JOIN 基表避免分组聚合行扇出翻倍；
    # 用 id IN 子查询代替全量拉 id（大数据量友好）。条件构建器条件已是标量安全，无需此步但无害。
    qs = ARRecord.objects.filter(id__in=qs.order_by().values('id'))

    group_by = request.GET.get('group_by', 'dept').strip() or 'dept'

    # NOTE: record-level sums (estimated/invoiced/outstanding/count) must NOT be
    # computed in the same query as Sum('payments__amount') — the payments JOIN
    # causes row fanout that multiplies record-level values. We always compute the
    # 回款 (collected) sum in a SEPARATE aggregate to keep both sides correct.
    def _amounts(sub_qs):
        base = sub_qs.aggregate(
            count=Count('id'),
            estimated=Sum('estimated_amount'),
            invoiced=Sum('actual_invoice_amount'),
            # Only sum positive outstanding — matches table rendering where
            # non-positive rows display "—" (treated as 0).
            outstanding=Sum('outstanding_amount', filter=Q(outstanding_amount__gt=0)),
        )
        collected = sub_qs.aggregate(s=Sum('payments__amount'))['s'] or 0
        return {
            'count': base['count'] or 0,
            'estimated': str(base['estimated'] or 0),
            'invoiced': str(base['invoiced'] or 0),
            'outstanding': str(base['outstanding'] or 0),
            'collected': str(collected),
        }

    rows = []
    if group_by == 'invoice_status':
        buckets = [
            ('未开票', qs.filter(actual_invoice_amount__isnull=True)),
            ('已结清', qs.filter(outstanding_amount__lte=0, actual_invoice_amount__isnull=False)),
            ('已开票', qs.filter(actual_invoice_amount__isnull=False, outstanding_amount__gt=0)),
        ]
        for label, sub in buckets:
            row = {'key': label, 'label': label}
            row.update(_amounts(sub))
            rows.append(row)
    elif group_by == 'month':
        # 运作年月：按 (年, 月) 分组，年月从高到低排序，下钻需带回年+月。
        agg_fields = ('operation_year', 'operation_month')
        base = qs.values(*agg_fields).annotate(
            count=Count('id'),
            estimated=Sum('estimated_amount'),
            invoiced=Sum('actual_invoice_amount'),
            outstanding=Sum('outstanding_amount', filter=Q(outstanding_amount__gt=0)),
        )
        collected_map = {
            (g['operation_year'], g['operation_month']): (g['collected'] or 0)
            for g in qs.values(*agg_fields).annotate(collected=Sum('payments__amount'))
        }
        ym_rows = []
        for g in base:
            y, m = g['operation_year'], g['operation_month']
            ym_rows.append({
                'key': f'{y}-{m}',
                'label': f'{y}年{m}月',
                'year': y, 'month': m,
                'count': g['count'] or 0,
                'estimated': str(g['estimated'] or 0),
                'invoiced': str(g['invoiced'] or 0),
                'outstanding': str(g['outstanding'] or 0),
                'collected': str(collected_map.get((y, m), 0)),
            })
        # 年月从高到低
        ym_rows.sort(key=lambda r: (r['year'], r['month']), reverse=True)
        rows = ym_rows
    elif group_by in _SUMMARY_GROUP_FIELDS:
        field, _ = _SUMMARY_GROUP_FIELDS[group_by]
        # Base record-level sums (no payments join → no fanout).
        # Filter outstanding to > 0 to match the table's "—" treatment of
        # non-positive values and avoid a negative group total.
        base = (qs.values(field).annotate(
            count=Count('id'),
            estimated=Sum('estimated_amount'),
            invoiced=Sum('actual_invoice_amount'),
            outstanding=Sum('outstanding_amount', filter=Q(outstanding_amount__gt=0)),
        ).order_by('-outstanding'))
        # Collected sums computed separately, keyed by the same group field
        collected_map = {
            g[field]: (g['collected'] or 0)
            for g in qs.values(field).annotate(collected=Sum('payments__amount'))
        }
        for g in base:
            raw_key = g[field]
            key = raw_key if raw_key not in (None, '') else '（未填写）'
            rows.append({
                'key': key,
                'label': str(key),
                'count': g['count'] or 0,
                'estimated': str(g['estimated'] or 0),
                'invoiced': str(g['invoiced'] or 0),
                'outstanding': str(g['outstanding'] or 0),
                'collected': str(collected_map.get(raw_key, 0)),
            })
        # 客户等级固定按 S→A→B→C→D 排序（其余置后）
        if group_by == 'customer_level':
            rows.sort(key=lambda r: _CUSTOMER_LEVEL_ORDER.get(r['key'], 99))
    else:
        return err(f'不支持的分组维度: {group_by}')

    return ok({'group_by': group_by, 'rows': rows})


# ══════════════════════════════════════════════════════════════════════════════
# 催款工作台 (collection workbench) — 逾期分桶 + 责任人聚合 + 一键生成催款行动项
# ══════════════════════════════════════════════════════════════════════════════

_DUNNING_BUCKETS = [
    ('d7',   '1-7天',    1,  7),
    ('d30',  '8-30天',   8,  30),
    ('d60',  '31-60天',  31, 60),
    ('d90',  '61-90天',  61, 90),
    ('d90p', '90天以上', 91, None),
]


def _overdue_qs(request, today):
    """当前用户可见范围内、仍有未收余额且已过应收日期的记录。"""
    qs = _ar_dept_filter(ARRecord.objects.select_related('project'), request,
                         shared_field='project__is_shared')
    return qs.filter(outstanding_amount__gt=0, due_date__isnull=False, due_date__lt=today)


def _bucket_cond(today, lo, hi):
    """逾期天数 ∈ [lo, hi] 对应的 due_date 区间条件（hi=None 表示不封顶）。"""
    cond = Q(due_date__lte=today - datetime.timedelta(days=lo))
    if hi:
        cond &= Q(due_date__gte=today - datetime.timedelta(days=hi))
    return cond


def _open_dunning_actions(record_ids=None):
    """record_id → 未关闭催款行动项 id。通过 source_signal.ar_record_id 关联，
    用于工作台标记「已有催款任务」并在批量生成时去重。"""
    qs = (ActionItem.objects.filter(category='collection',
                                    status__in=['open', 'in_progress'])
          .only('id', 'source_signal'))
    out = {}
    for item in qs:
        rid = (item.source_signal or {}).get('ar_record_id')
        if rid is None:
            continue
        if record_ids is not None and rid not in record_ids:
            continue
        out[rid] = item.id
    return out


@csrf_exempt
@pk_required()
def ar_collection_workbench(request):
    """催款工作台：逾期应收按账龄分桶 + 责任人（销售对接人）聚合 + 明细列表。
    明细带「已有催款任务」标记，与决策行动（ActionItem）打通。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    denied = _ar_field_denied(request, 'r_outstanding')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)

    today = datetime.date.today()
    qs = _overdue_qs(request, today)
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(project__short_name__icontains=q) |
            Q(project__customer_name__icontains=q) |
            Q(project__project_no__icontains=q) |
            Q(project__sales_contact__icontains=q))

    # 分桶统计（基于 dept/q 筛选后的全量逾期集，不随 bucket/contact 细分变化）
    buckets = []
    for key, label, lo, hi in _DUNNING_BUCKETS:
        agg = qs.filter(_bucket_cond(today, lo, hi)).aggregate(
            count=Count('id'), amount=Sum('outstanding_amount'))
        buckets.append({'key': key, 'label': label,
                        'count': agg['count'] or 0, 'amount': str(agg['amount'] or 0)})

    # 责任人聚合：销售对接人（回款责任人）维度，按未收金额降序
    by_contact = []
    contact_agg = (qs.values('project__sales_contact')
                   .annotate(count=Count('id'), amount=Sum('outstanding_amount'),
                             oldest_due=Min('due_date'))
                   .order_by('-amount'))
    for g in contact_agg:
        by_contact.append({
            'sales_contact': g['project__sales_contact'] or '（未填写）',
            'count': g['count'],
            'amount': str(g['amount'] or 0),
            'max_overdue_days': (today - g['oldest_due']).days if g['oldest_due'] else 0,
        })

    # 明细：可再按 bucket / 责任人 细分
    items_qs = qs
    bucket = request.GET.get('bucket', '').strip()
    if bucket:
        spec = next((b for b in _DUNNING_BUCKETS if b[0] == bucket), None)
        if spec:
            items_qs = items_qs.filter(_bucket_cond(today, spec[2], spec[3]))
    contact = request.GET.get('contact', '').strip()
    if contact:
        if contact == '（未填写）':
            items_qs = items_qs.filter(project__sales_contact='')
        else:
            items_qs = items_qs.filter(project__sales_contact=contact)

    sum_agg = items_qs.aggregate(count=Count('id'), amount=Sum('outstanding_amount'))
    page = max(1, int(request.GET.get('page', 1) or 1))
    size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
    page_qs = (items_qs.annotate(last_pay=Max('payments__payment_date'))
               .order_by('due_date', 'id')[(page - 1) * size: page * size])
    rows = list(page_qs)
    open_actions = _open_dunning_actions({r.id for r in rows})

    items = []
    for rec in rows:
        proj = rec.project
        items.append({
            'id': rec.id,
            'project_id': rec.project_id,
            'project_no': proj.project_no,
            'short_name': proj.short_name,
            'customer_name': proj.customer_name,
            'delivery_dept': rec.delivery_dept,
            'sales_contact': proj.sales_contact,
            'project_manager': proj.project_manager,
            'operation_year': rec.operation_year,
            'operation_month': rec.operation_month,
            'estimated_amount': str(rec.estimated_amount),
            'outstanding_amount': str(rec.outstanding_amount),
            'due_date': str(rec.due_date),
            'overdue_days': (today - rec.due_date).days,
            'invoice_status': rec.invoice_status,
            'last_payment_date': str(rec.last_pay) if rec.last_pay else None,
            'open_action_id': open_actions.get(rec.id),
        })

    return ok({
        'buckets': buckets,
        'by_contact': by_contact,
        'items': items,
        'total': sum_agg['count'] or 0,
        'page': page, 'size': size,
        'summary': {'count': sum_agg['count'] or 0, 'amount': str(sum_agg['amount'] or 0)},
    })


@csrf_exempt
@pk_required()
def ar_collection_dunning(request):
    """批量生成催款行动项：每条逾期应收一条；已有未关闭催款任务的记录自动跳过。
    生成的行动项出现在财务驾驶舱「决策行动」Tab（category=collection）。"""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    denied = _write_denied(request)
    if denied:
        return denied

    data = _parse_body(request)
    try:
        id_list = [int(i) for i in (data.get('ids') or [])]
    except (ValueError, TypeError):
        return err('ids 参数格式错误')
    if not id_list:
        return err('请先选择要催款的记录')
    if len(id_list) > 200:
        return err('单次最多生成200条催款任务')

    today = datetime.date.today()
    # 走 _overdue_qs 复核：只允许对可见范围内、确实逾期未收的记录生成任务
    recs = list(_overdue_qs(request, today).filter(pk__in=id_list))
    existing = _open_dunning_actions({r.id for r in recs})
    assignee_override = (data.get('assignee') or '').strip()
    follow_days = 7
    try:
        follow_days = max(1, min(90, int(data.get('follow_days', 7))))
    except (ValueError, TypeError):
        pass

    created = []
    skipped = 0
    for rec in recs:
        if rec.id in existing:
            skipped += 1
            continue
        proj = rec.project
        days = (today - rec.due_date).days
        item = ActionItem(
            title=(f'催款：{proj.short_name or proj.customer_name} '
                   f'{rec.operation_year}/{rec.operation_month:02d} '
                   f'逾期{days}天 ¥{rec.outstanding_amount:,.2f}'),
            description=(f'项目 {proj.project_no} · 客户 {proj.customer_name} · '
                         f'应收日期 {rec.due_date} · 未收 {rec.outstanding_amount:,.2f} 元 · '
                         f'销售对接人 {proj.sales_contact or "未填写"}'),
            bu=rec.delivery_dept,
            category='collection',
            priority='high' if days > 30 else 'medium',
            assignee=assignee_override or proj.sales_contact or '',
            due_date=today + datetime.timedelta(days=follow_days),
            source_signal={'ar_record_id': rec.id, 'project_no': proj.project_no,
                           'outstanding': str(rec.outstanding_amount),
                           'overdue_days': days},
            created_by=request.pk_user,
        )
        item.save()
        created.append(item.id)

    return ok({'created': len(created), 'skipped': skipped, 'action_ids': created,
               'missing': len(id_list) - len(recs)})


# ══════════════════════════════════════════════════════════════════════════════
# Payments sub-resource
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@pk_required()
def ar_payments(request, pk):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    try:
        rec = ARRecord.objects.select_related('project').get(pk=pk)
    except ARRecord.DoesNotExist:
        return err('记录不存在', 404)
    if request.pk_role != 'super_admin':
        allowed = request.pk_depts
        if rec.delivery_dept not in allowed:
            return err('无权访问', 403)
    denied = _ar_field_denied(request, 'r_payments')
    if denied:
        return denied

    if request.method == 'GET':
        pays = list(rec.payments.order_by('payment_no'))
        return ok([p.to_dict() for p in pays])

    if request.method == 'POST':
        denied = _action_denied(request, 'ar_collect')
        if denied:
            return denied
        data = _parse_body(request)
        amount = _dec(data.get('amount', 0))
        if amount <= 0:
            return err('金额必须大于0')
        pay_date = _normalize_date(data.get('payment_date'))
        if not pay_date:
            return err('日期无效')
        # 来源：'回款'（现金）或 '内部往来'（事业部间核销，不计现金）。
        # '预收抵扣' 仅由预收核销自动生成，禁止经此接口手工录入。
        source = (data.get('source') or '回款').strip()
        counterparty = (data.get('counterparty_dept') or '').strip()
        if source == '预收抵扣':
            return err('预收抵扣由预收核销自动生成，请在「预收预付」页操作')
        if source not in ('回款', '内部往来'):
            return err('回款来源无效')
        if source == '内部往来':
            if counterparty not in VALID_DEPARTMENTS:
                return err('内部往来核销须选择有效的往来事业部')
        else:
            counterparty = ''   # 现金回款不带往来部门
        try:
            with transaction.atomic():
                last = rec.payments.select_for_update().order_by('-payment_no').first()
                next_no = (last.payment_no + 1) if last else 1
                pay = ARPayment.objects.create(
                    ar_record=rec,
                    payment_no=next_no,
                    amount=amount,
                    payment_date=pay_date,
                    source=source,
                    counterparty_dept=counterparty,
                    notes=data.get('notes', '').strip(),
                )
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok(pay.to_dict())

    return err('Method not allowed', 405)


def _adjustments_payload(rec):
    """调整明细变更后的统一回包：明细列表 + 派生合计 + 最新未收（UI 一次刷新）。"""
    rec.refresh_from_db()
    return {
        'items': [a.to_dict() for a in rec.adjustments.all()],
        'total_adjustment': str(rec.account_diff_adjustment or 0),
        'outstanding_amount': str(rec.outstanding_amount or 0),
    }


@csrf_exempt
@pk_required()
def ar_adjustments(request, pk):
    """GET/POST /records/<pk>/adjustments — 差额调整明细（多次、各带原因与金额）。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    try:
        rec = ARRecord.objects.select_related('project').get(pk=pk)
    except ARRecord.DoesNotExist:
        return err('记录不存在', 404)
    if request.pk_role != 'super_admin' and rec.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    denied = _ar_field_denied(request, 'r_account_diff')
    if denied:
        return denied

    if request.method == 'GET':
        return ok(_adjustments_payload(rec))

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        amount = _dec(data.get('amount', 0))
        if not amount:
            return err('调整金额不能为0（可正可负）')
        reason = (data.get('reason') or '').strip()
        if not reason:
            return err('请填写调整原因（如：运费差、客户扣款、补付、四舍五入）')
        from paikuan.models import PaikuanUser
        try:
            with transaction.atomic():
                ARAdjustment.objects.create(
                    ar_record=rec, amount=amount, reason=reason[:200],
                    adjust_date=_normalize_date(data.get('adjust_date')) or None,
                    created_by=PaikuanUser.objects.filter(id=request.pk_uid).first())
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok(_adjustments_payload(rec))

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_adjustment_detail(request, pk, aid):
    """DELETE /records/<pk>/adjustments/<aid> — 删除一笔调整（合计随之回退）。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'DELETE':
        return err('Method not allowed', 405)
    denied = _write_denied(request)
    if denied:
        return denied
    try:
        adj = ARAdjustment.objects.select_related('ar_record').get(pk=aid, ar_record_id=pk)
    except ARAdjustment.DoesNotExist:
        return err('调整明细不存在', 404)
    rec = adj.ar_record
    if request.pk_role != 'super_admin' and rec.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    denied = _ar_field_denied(request, 'r_account_diff')
    if denied:
        return denied
    try:
        with transaction.atomic():
            adj.delete()
    except ValidationError as e:
        # 删除该调整会使未收为负（累计回款已超过 上账+剩余差额）→ 拒绝
        return err(str(e.message if hasattr(e, 'message') else e), 400)
    return ok(_adjustments_payload(rec))


@csrf_exempt
@pk_required()
def ar_payment_detail(request, pk, ppk):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    try:
        pay = ARPayment.objects.select_related('ar_record__project').get(
            pk=ppk, ar_record_id=pk)
    except ARPayment.DoesNotExist:
        return err('回款记录不存在', 404)
    if request.pk_role != 'super_admin':
        allowed = request.pk_depts
        if pay.ar_record.delivery_dept not in allowed:
            return err('无权访问', 403)
        perms = get_request_perms(request)
        if perms and perms.get('ar_shared_only') and not pay.ar_record.project.is_shared:
            return err('无权访问', 403)
    denied = _ar_field_denied(request, 'r_payments')
    if denied:
        return denied

    # 「预收抵扣」回款由预收核销自动生成：金额/日期须在核销侧改（PUT 禁止）；
    # DELETE 即「反向核销」——删除对应预收核销，预收余额恢复、回款级联删除。
    if pay.source == '预收抵扣' and request.method == 'PUT':
        return err('该回款由预收核销生成，请在「预收预付」页修改对应核销，或删除后重新核销', 400)
    if pay.source == '预收抵扣' and request.method == 'DELETE':
        denied = _action_denied(request, 'wo_receive')
        if denied:
            return denied
        wo = AdvanceWriteoff.objects.filter(ar_payment_id=pay.pk).first()
        if wo is None:
            # 核销已不存在（历史数据异常）：直接删孤儿回款，恢复应收
            with transaction.atomic():
                pay.delete()
            return ok({'deleted': ppk, 'reversed_writeoff': None})
        wo_id = wo.pk
        try:
            with transaction.atomic():
                wo.delete()   # 信号级联删本回款 + 重算应收未收与预收余额
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok({'deleted': ppk, 'reversed_writeoff': wo_id,
                   'message': '已反向核销：预收余额恢复，应收未收回升'})

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        if 'amount' in data:
            amount = _dec(data['amount'])
            if amount <= 0:
                return err('金额必须大于0')
            pay.amount = amount
        if 'payment_date' in data:
            pay.payment_date = _normalize_date(data['payment_date']) or pay.payment_date
        # 往来部门仅对内部往来核销有意义，且必须是有效事业部
        if 'counterparty_dept' in data and pay.source == '内部往来':
            cp = (data['counterparty_dept'] or '').strip()
            if cp not in VALID_DEPARTMENTS:
                return err('内部往来核销须选择有效的往来事业部')
            pay.counterparty_dept = cp
        if 'notes' in data:
            pay.notes = data['notes'].strip()
        try:
            pay.save()
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok(pay.to_dict())

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        pay.delete()
        return ok({'deleted': ppk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_record_recompute(request, pk):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _write_denied(request)
    if denied:
        return denied
    try:
        rec = ARRecord.objects.select_related('project').get(pk=pk)
    except ARRecord.DoesNotExist:
        return err('记录不存在', 404)
    denied = _object_dept_denied(request, rec)
    if denied:
        return denied
    rec.recompute_derived(save=True)
    rec.save(update_fields=['updated_at'])
    return ok({'id': rec.id, 'outstanding_amount': str(rec.outstanding_amount)})


# ══════════════════════════════════════════════════════════════════════════════
# Data health — detect inconsistent records left by legacy-template imports
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@pk_required()
def ar_data_health(request):
    """扫描应收明细，找出口径异常的记录（多为旧模板导入产生的废数据）。

    分两类：
    - negative：预估上账 + 账实差额 − 累计回款 < 0（累计回款超过上账口径），
      不能自动修复，需人工核对预估金额/账实差额/回款明细。
    - stale：存储的未收金额与按现规则重算的结果不一致，但重算结果 ≥ 0，
      可一键重算修复。
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'GET':
        return err('GET only', 405)

    qs = _ar_dept_filter(ARRecord.objects.select_related('project'), request,
                         shared_field='project__is_shared')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    qs = qs.annotate(_paid=Sum('payments__amount'))

    LIMIT = 300
    negative, stale = [], []
    neg_count = stale_count = 0
    for rec in qs.iterator():
        base = rec.estimated_amount or Decimal('0')
        adj = rec.account_diff_adjustment or Decimal('0')
        paid = rec._paid or Decimal('0')
        recomputed = base + adj - paid
        stored = rec.outstanding_amount
        if recomputed < Decimal('0'):
            neg_count += 1
            if len(negative) < LIMIT:
                negative.append({
                    'id': rec.id,
                    'project_no': rec.project.project_no,
                    'short_name': rec.project.short_name or rec.project.customer_name,
                    'delivery_dept': rec.delivery_dept,
                    'operation_year': rec.operation_year,
                    'operation_month': rec.operation_month,
                    'estimated_amount': str(base),
                    'account_diff_adjustment': str(adj),
                    'total_paid': str(paid),
                    'stored_outstanding': str(stored) if stored is not None else None,
                    'deficit': str(-recomputed),
                })
        elif stored is None or stored != recomputed:
            stale_count += 1
            if len(stale) < LIMIT:
                stale.append({
                    'id': rec.id,
                    'project_no': rec.project.project_no,
                    'short_name': rec.project.short_name or rec.project.customer_name,
                    'delivery_dept': rec.delivery_dept,
                    'operation_year': rec.operation_year,
                    'operation_month': rec.operation_month,
                    'estimated_amount': str(base),
                    'account_diff_adjustment': str(adj),
                    'total_paid': str(paid),
                    'stored_outstanding': str(stored) if stored is not None else None,
                    'recomputed_outstanding': str(recomputed),
                })
    return ok({
        'negative_count': neg_count, 'stale_count': stale_count,
        'negative': negative, 'stale': stale, 'limit': LIMIT,
        'has_issues': bool(neg_count or stale_count),
    })


@csrf_exempt
@pk_required()
def ar_records_recompute_bulk(request):
    """按现规则批量重算指定记录的未收金额/税额，用于一键修复 stale 记录。
    会跳过重算后未收为负的记录（这类需人工处理）。Body: {ids: [int, ...]}。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _write_denied(request)
    if denied:
        return denied
    body = _parse_body(request)
    ids = body.get('ids') or []
    if not isinstance(ids, list) or not ids:
        return err('请提供要重算的记录 ids')
    try:
        ids = [int(i) for i in ids][:1000]
    except (ValueError, TypeError):
        return err('ids 必须为整数列表')

    qs = _ar_dept_filter(ARRecord.objects.select_related('project').filter(pk__in=ids),
                         request, shared_field='project__is_shared')
    fixed, failed = 0, []
    for rec in qs:
        if request.pk_role != 'super_admin' and rec.delivery_dept not in (request.pk_depts or []):
            failed.append({'id': rec.id, 'msg': '无权操作此部门'})
            continue
        try:
            rec.recompute_derived(save=True)
            fixed += 1
        except ValidationError as e:
            failed.append({'id': rec.id,
                           'msg': str(e.message if hasattr(e, 'message') else e)})
    return ok({'fixed': fixed, 'failed': failed})


@csrf_exempt
@pk_required()
def ar_records_bulk_delete(request):
    """批量删除应收明细（级联回款）。两种模式：
      - 显式选择：body {ids:[int,...]}
      - 选择全部筛选集：body {all:true} + 查询串里的 conditions/match（与列表同口径）
    始终受部门作用域与删除权限约束；单次上限 5000 条，防误删全库。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _delete_denied(request)
    if denied:
        return denied

    body = _parse_body(request)
    today = datetime.date.today()
    base = _ar_dept_filter(ARRecord.objects.select_related('project'), request,
                           shared_field='project__is_shared')

    if body.get('all'):
        # 与列表完全相同的筛选口径（conditions/match 走查询串）
        qs = _apply_record_filters(base, request)
        qs = _apply_record_state_filters(qs, request, today)
        qs = _apply_conditions(qs, request, today)
    else:
        ids = body.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return err('请提供要删除的记录 ids')
        try:
            ids = [int(i) for i in ids]
        except (ValueError, TypeError):
            return err('ids 必须为整数列表')
        qs = base.filter(pk__in=ids)

    # 非超管：再次按可操作部门收紧，杜绝越权删除
    if request.pk_role != 'super_admin':
        qs = qs.filter(delivery_dept__in=(request.pk_depts or []))

    count = qs.count()
    if count == 0:
        return ok({'deleted': 0})
    if count > 5000:
        return err('单次删除上限 5000 条，请先缩小筛选范围')
    # 取 id 后用主键集删除：避免子查询/JOIN 在 delete 级联时的边界问题
    del_ids = list(qs.values_list('id', flat=True))
    ARRecord.objects.filter(pk__in=del_ids).delete()  # 级联删除关联回款
    return ok({'deleted': len(del_ids)})



# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
