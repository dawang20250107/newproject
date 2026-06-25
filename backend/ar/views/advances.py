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
        today = datetime.date.today()
        qs = _advance_dept_filter(
            AdvanceRecord.objects.select_related('project', 'created_by'), request)
        qs = _apply_advance_filters(qs, request)
        # 列头排序仅作用于分页列表（汇总不受影响）；非法/未指定回退模型默认排序
        sort_by = resolve_sort(request.GET.get('sort'), request.GET.get('order'),
                               ADVANCE_FILTER_REGISTRY)
        if sort_by:
            qs = qs.order_by(sort_by)
        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))

        qs_agg = _apply_advance_filters(
            _advance_dept_filter(AdvanceRecord.objects.all(), request), request)
        ids = list(qs_agg.order_by().values_list('id', flat=True))
        total = len(ids)
        base = AdvanceRecord.objects.filter(id__in=ids)

        def _dir_summary(direction):
            d_qs = base.filter(direction=direction)
            agg = d_qs.aggregate(
                amt=Sum('advance_amount'),
                wo=Sum('written_off_amount'),
                bal=Sum('balance_amount', filter=Q(balance_amount__gt=0)),
            )
            overdue = (d_qs.filter(balance_amount__gt=0,
                                   expected_writeoff_date__lt=today)
                       .aggregate(s=Sum('balance_amount'))['s'] or 0)
            return {
                'count': d_qs.count(),
                'advance_amount': str(agg['amt'] or 0),
                'written_off': str(agg['wo'] or 0),
                'balance': str(agg['bal'] or 0),
                'overdue_balance': str(overdue),
            }

        summary = {
            'count': total,
            '预收': _dir_summary('预收'),
            '预付': _dir_summary('预付'),
        }

        perms = get_request_perms(request)
        include_wo = request.GET.get('include_writeoffs', '') in ('1', 'true')
        items = list(qs[(page - 1) * size: page * size])
        rows = [apply_ar_view_mask(r.to_dict(today=today, include_writeoffs=include_wo),
                                   perms, 'advance') for r in items]
        return ok({'items': rows, 'total': total, 'page': page, 'size': size,
                   'summary': summary})

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
        rec.to_dict(today=datetime.date.today(), include_writeoffs=True),
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
    today = datetime.date.today()

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
                            amount=delta, occur_date=rec.occur_date or datetime.date.today(),
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
        rec.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def advances_kpi(request):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    today = datetime.date.today()
    qs = _apply_advance_filters(
        _advance_dept_filter(AdvanceRecord.objects.all(), request), request)

    def _block(direction):
        d_qs = qs.filter(direction=direction)
        agg = d_qs.aggregate(amt=Sum('advance_amount'), wo=Sum('written_off_amount'),
                             bal=Sum('balance_amount', filter=Q(balance_amount__gt=0)))
        total_amt = float(agg['amt'] or 0)
        wo = float(agg['wo'] or 0)
        bal = float(agg['bal'] or 0)
        pending = d_qs.filter(balance_amount__gt=0).count()
        overdue_qs = d_qs.filter(balance_amount__gt=0, expected_writeoff_date__lt=today)
        overdue_amt = float(overdue_qs.aggregate(s=Sum('balance_amount'))['s'] or 0)
        return {
            'count': d_qs.count(),
            'advance_amount': total_amt,
            'written_off': wo,
            'balance': bal,
            'writeoff_rate': round(wo / total_amt * 100, 1) if total_amt else 100.0,
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
        agg = (qs.values('occur_year', 'occur_month')
               .annotate(count=Count('id'), advance_amount=Sum('advance_amount'),
                         written_off=Sum('written_off_amount'),
                         balance=Sum('balance_amount'))
               .order_by('occur_year', 'occur_month'))
        for r in agg:
            rows.append({
                'key': f"{r['occur_year']}-{r['occur_month']:02d}",
                'year': r['occur_year'], 'month': r['occur_month'],
                'count': r['count'],
                'advance_amount': str(r['advance_amount'] or 0),
                'written_off': str(r['written_off'] or 0),
                'balance': str(r['balance'] or 0),
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
    today = datetime.date.today()
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
    try:
        wb = openpyxl.load_workbook(f, data_only=True)
        ws = wb.active
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
        year = int(_cv(ri, '发生年*') or 0)
        month = int(_cv(ri, '发生月*') or 0)
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
        with transaction.atomic():
            for p in plan:
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

    return ok({'created': created, 'updated': 0, 'skipped': 0, 'errors': []})


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
    today = datetime.date.today()
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
        (None, '发生年', lambda rec, st: rec.occur_year),
        (None, '发生月', lambda rec, st: rec.occur_month),
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
    return _export_response(wb, '预收预付明细.xlsx')


@csrf_exempt
@pk_required()
def advance_writeoffs(request, pk):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    try:
        rec = AdvanceRecord.objects.select_related('project').get(pk=pk)
    except AdvanceRecord.DoesNotExist:
        return err('记录不存在', 404)
    if request.pk_role != 'super_admin' and rec.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    denied = _ar_field_denied(request, 'adv_writeoff')
    if denied:
        return denied

    if request.method == 'GET':
        return ok([w.to_dict() for w in
                   rec.writeoffs.select_related('payment').order_by('writeoff_no')])

    if request.method == 'POST':
        denied = _action_denied(request,
                                'wo_receive' if rec.direction == '预收' else 'wo_prepaid')
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
                payment_obj = Payment.objects.get(pk=int(payment_id))
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
    if request.method != 'GET':
        return err('Method not allowed', 405)
    dept = (request.GET.get('dept') or '').strip()
    q = (request.GET.get('q') or '').strip().lower()

    qs = (_advance_dept_filter(AdvanceRecord.objects.select_related('project'), request)
          .filter(project__isnull=False)
          .prefetch_related('installments'))
    if dept:
        qs = qs.filter(delivery_dept=dept)

    groups = {}
    for a in qs.order_by('occur_date', 'id'):
        name = (a.project.short_name or '').strip()
        if not name:
            continue
        if q and q not in name.lower():
            continue
        g = groups.setdefault(name, {
            'project': name,
            'dept': a.project.delivery_dept or a.delivery_dept or '',
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
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    try:
        wo = AdvanceWriteoff.objects.select_related('advance_record__project').get(
            pk=wid, advance_record_id=pk)
    except AdvanceWriteoff.DoesNotExist:
        return err('核销记录不存在', 404)
    if request.pk_role != 'super_admin' and wo.advance_record.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)
    denied = _ar_field_denied(request, 'adv_writeoff')
    if denied:
        return denied

    _wo_action = 'wo_receive' if wo.advance_record.direction == '预收' else 'wo_prepaid'
    if request.method == 'PUT':
        denied = _action_denied(request, _wo_action)
        if denied:
            return denied
        data = _parse_body(request)
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
            wo.amount = new_amount
        if 'writeoff_date' in data:
            wo.writeoff_date = _normalize_date(data['writeoff_date']) or wo.writeoff_date
        if 'notes' in data:
            wo.notes = (data['notes'] or '').strip()
        try:
            with transaction.atomic():
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




# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
