"""预算（budget）业务域：回款预算/付款预算 列表·详情·模板·导入导出·汇总·项目对比。共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

# ══════════════════════════════════════════════════════════════════════════════
# Budget
# ══════════════════════════════════════════════════════════════════════════════

def _budget_list_create(request, Model, page_key):
    denied = _page_denied(request, page_key)
    if denied:
        return denied

    if request.method == 'GET':
        qs = _ar_dept_filter(Model.objects.select_related('created_by'), request,
                             dept_field='delivery_dept')
        dept = request.GET.get('dept', '').strip()
        if dept:
            qs = qs.filter(delivery_dept=dept)
        _today = datetime.date.today()
        _ds, _de = _parse_budget_date_range(request, _today)
        qs = qs.filter(expected_date__gte=_ds, expected_date__lte=_de)
        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
        total = qs.count()
        items = [obj.to_dict() for obj in qs[(page - 1) * size: page * size]]
        total_amount = str(qs.aggregate(s=Sum('amount'))['s'] or 0)
        return ok({'items': items, 'total': total, 'page': page, 'size': size,
                   'total_amount': total_amount})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        dept = data.get('delivery_dept', '').strip()
        short_name = data.get('short_name', '').strip()
        # Auto-derive dept from matched project when caller omits delivery_dept
        if not dept and short_name:
            search_depts = None if request.pk_role == 'super_admin' else request.pk_depts
            _pre_proj = _match_project_by_short_name(short_name, allowed_depts=search_depts)
            if _pre_proj:
                dept = _pre_proj.delivery_dept
        if dept and dept not in VALID_DEPARTMENTS:
            return err(f'无效交付部门: {dept}')
        denied = _dept_denied(request, dept, '无权操作此部门')
        if denied:
            return denied
        date_str = _normalize_date(data.get('expected_date'))
        if not date_str:
            return err('预计日期无效，请填 2026-06-15 这样的格式（也支持 2026/6/15、2026年6月15日）')
        amount = _dec(data.get('amount', 0))
        if amount <= 0:
            return err('金额必须大于0')
        from paikuan.models import PaikuanUser
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        proj = _match_project_by_short_name(short_name, dept)
        auto_project_no = proj.project_no if proj else data.get('project_no', '').strip()
        auto_sub_dept = proj.sub_dept if proj else data.get('sub_dept', '').strip()
        obj = Model.objects.create(
            project_no=auto_project_no,
            short_name=short_name,
            expected_date=date_str,
            sub_dept=auto_sub_dept,
            delivery_dept=dept,
            amount=amount,
            notes=data.get('notes', '').strip(),
            created_by=user,
        )
        return ok(obj.to_dict())

    return err('Method not allowed', 405)


def _budget_detail(request, pk, Model, page_key):
    denied = _page_denied(request, page_key)
    if denied:
        return denied
    try:
        obj = Model.objects.get(pk=pk)
    except Model.DoesNotExist:
        return err('记录不存在', 404)
    denied = _object_dept_denied(request, obj)
    if denied:
        return denied

    if request.method == 'GET':
        return ok(obj.to_dict())

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        for field in ('project_no', 'short_name', 'sub_dept', 'notes'):
            if field in data:
                setattr(obj, field, data[field])
        if 'delivery_dept' in data:
            dept = data['delivery_dept']
            if dept and dept not in VALID_DEPARTMENTS:
                return err(f'无效交付部门: {dept}')
            denied = _dept_denied(request, dept, '无权操作目标部门')
            if denied:
                return denied
            obj.delivery_dept = dept
        if 'expected_date' in data:
            obj.expected_date = _normalize_date(data['expected_date']) or obj.expected_date
        if 'amount' in data:
            amount = _dec(data['amount'])
            if amount <= 0:
                return err('金额必须大于0')
            obj.amount = amount
        obj.save()
        return ok(obj.to_dict())

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        obj.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def budget_collection(request):
    return _budget_list_create(request, CollectionBudget, 'ar_budget')


@csrf_exempt
@pk_required()
def budget_collection_detail(request, pk):
    return _budget_detail(request, pk, CollectionBudget, 'ar_budget')


@csrf_exempt
@pk_required()
def budget_payment(request):
    return _budget_list_create(request, PaymentBudget, 'ar_budget')


@csrf_exempt
@pk_required()
def budget_payment_detail(request, pk):
    return _budget_detail(request, pk, PaymentBudget, 'ar_budget')


def _parse_budget_date_range(request, today):
    """Return (start_date, end_date) from date_start/date_end GET params.
    Defaults to the current month when neither param is supplied."""
    ds = request.GET.get('date_start', '').strip()
    de = request.GET.get('date_end', '').strip()
    try:
        start = datetime.date.fromisoformat(ds) if ds else None
    except ValueError:
        start = None
    try:
        end = datetime.date.fromisoformat(de) if de else None
    except ValueError:
        end = None
    if not start and not end:
        start = datetime.date(today.year, today.month, 1)
        end = datetime.date(today.year, today.month,
                            calendar.monthrange(today.year, today.month)[1])
    elif not start:
        start = datetime.date(end.year, end.month, 1)
    elif not end:
        end = datetime.date(start.year, start.month,
                            calendar.monthrange(start.year, start.month)[1])
    return start, end


def _budget_label(kind):
    return '收款' if kind == 'collection' else '付款'


def _budget_template(request, kind):
    denied = _page_denied(request, 'ar_budget')
    if denied:
        return denied
    lbl = _budget_label(kind)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f'{lbl}预算'
    headers = ['项目编号(可选)', '项目简称/摘要*', f'预计{lbl}日期*',
               '二级部门', '交付部门', '金额*', '备注']
    color = '1B6E35' if kind == 'collection' else 'B25600'
    _header_row(ws, headers, color=color)

    # 第2行：填写说明（导入时自动跳过——简称列以 ★ 开头）
    tips = [
        '选填：项目编号；留空会按简称自动从台账带入',
        f'★必填：项目台账中的"项目简称"（精确匹配；同名多项目时用"交付部门"列消歧）',
        f'★必填：预计{lbl}日期，格式 2026-06-15 / 2026/6/15 / 2026年6月15日 均可；'
        '若单元格被Excel识别为日期格式也可直接选日期',
        '选填：二级部门；留空或填错会按台账自动更正',
        '选填：交付部门；留空会按台账带入，仅在简称重名时用于区分',
        '★必填：金额（元），须大于 0',
        '选填：备注',
    ]
    ws.append(tips)
    tip_row = ws.max_row
    tip_fill = PatternFill('solid', fgColor='FFF8E1' if kind == 'collection' else 'FFF3E0')
    tip_font = Font(italic=True, color='6D4C00', size=9)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(tip_row, c)
        cell.fill = tip_fill
        cell.font = tip_font
        cell.alignment = Alignment(wrap_text=True, vertical='top')
    ws.row_dimensions[tip_row].height = 56

    # 第3行：示例（简称列含"示例"标记，导入时自动跳过）
    ws.append(['', f'{EXAMPLE_ROW_MARKER}示例项目A', '2026-06-15', '华南区',
               '劳务事业部', 100000, '填对项目简称即可，编号/交付部门/二级部门会自动按台账带入或更正'])
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 22
    return _export_response(wb, f'{lbl}预算导入模板.xlsx')


def _budget_import(request, Model, kind):
    denied = _page_denied(request, 'ar_budget')
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
    lbl = _budget_label(kind)

    def _cv(row, name):
        idx = col_map.get(name)
        if idx is None:
            return ''
        v = ws.cell(row, idx).value
        return str(v).strip() if v is not None else ''

    # 日期列名：新模板用"预计X日期*"，旧模板用"预计X日期(YYYY-MM-DD)*"，两者都兼容。
    date_col_names = [f'预计{lbl}日期*', f'预计{lbl}日期(YYYY-MM-DD)*',
                      f'预计{lbl}日期']

    def _raw_first(row, names):
        # Return the first matching cell's RAW value (not stringified) so that
        # openpyxl-typed dates reach _normalize_date intact. Excel-recognised date
        # cells come back as datetime objects; str() would yield
        # '2026-06-15 00:00:00', which _normalize_date cannot parse — that was the
        # "预计日期无效" failure on template-filled rows.
        for n in names:
            if n in col_map:
                return ws.cell(row, col_map[n]).value
        return None

    def _cv_first(row, names):
        for n in names:
            if n in col_map:
                v = ws.cell(row, col_map[n]).value
                return str(v).strip() if v is not None else ''
        return ''

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    search_depts = None if request.pk_role == 'super_admin' else request.pk_depts
    corrected = 0
    errors = []
    warnings = []
    plan = []   # 通过校验、待写入的行

    # ══ 阶段一：逐行校验 + 按台账自动更正（不写库）。示例/空行静默忽略 ══════════════
    for ri in range(2, ws.max_row + 1):
        short_name = _cv(ri, '项目简称/摘要*')
        # 示例/提示行、必填摘要为空：静默忽略（不计入、不报错）
        if not short_name or EXAMPLE_ROW_MARKER in short_name or short_name.startswith('★'):
            continue
        date_str = _normalize_date(_raw_first(ri, date_col_names))
        if not date_str:
            raw_date = _cv_first(ri, date_col_names)
            hint = f'（读到"{raw_date}"）' if raw_date else '（该格为空）'
            errors.append(f'第{ri}行: 预计{lbl}日期无效{hint}，请填 2026-06-15 这样的格式')
            continue
        filled_dept = _cv(ri, '交付部门')

        # 项目简称是权威来源：先只按简称匹配项目（忽略可能填错的部门列）。
        # 简称对应多个部门时，用填写的交付部门消歧。
        name_matches = list(ARProject.objects.filter(short_name=short_name.strip()))
        if search_depts is not None:
            name_matches = [m for m in name_matches if m.delivery_dept in search_depts]
        proj = None
        if len(name_matches) == 1:
            proj = name_matches[0]
        elif len(name_matches) > 1:
            cands = [m for m in name_matches if m.delivery_dept == filled_dept] if filled_dept else []
            if len(cands) == 1:
                proj = cands[0]
            else:
                depts_hint = '、'.join(sorted({m.delivery_dept for m in name_matches}))
                errors.append(f'第{ri}行: 项目简称"{short_name}"对应多个部门（{depts_hint}），'
                              f'请在"交付部门"列填写正确部门以区分')
                continue
        else:
            # 简称无精确匹配，回退到模糊匹配（容许用户填部分简称）
            proj = _match_project_by_short_name(short_name, filled_dept, search_depts)

        if proj:
            # 以台账为准：用项目的编号/部门/二级部门覆盖填写值（自动更正，不算跳过）
            dept = proj.delivery_dept
            project_no = proj.project_no
            sub_dept = proj.sub_dept
            mismatches = []
            if filled_dept and filled_dept != dept:
                mismatches.append(f'交付部门"{filled_dept}"→"{dept}"')
            filled_no = _cv(ri, '项目编号(可选)')
            if filled_no and filled_no != project_no:
                mismatches.append(f'项目编号"{filled_no}"→"{project_no}"')
            filled_sub = _cv(ri, '二级部门')
            if filled_sub and filled_sub != sub_dept:
                mismatches.append(f'二级部门"{filled_sub}"→"{sub_dept}"')
            if mismatches:
                corrected += 1
                warnings.append(f'第{ri}行: 已按项目台账自动更正（{"，".join(mismatches)}）')
        else:
            # 自由文本摘要（非台账项目）：采用填写值
            dept = filled_dept
            project_no = _cv(ri, '项目编号(可选)')
            sub_dept = _cv(ri, '二级部门')

        if dept and dept not in VALID_DEPARTMENTS:
            errors.append(f'第{ri}行: 无效交付部门"{dept}"，可选值为：{"/".join(VALID_DEPARTMENTS)}')
            continue
        if request.pk_role != 'super_admin' and dept not in request.pk_depts:
            errors.append(f'第{ri}行: 无权操作部门"{dept}"')
            continue
        amount = _dec(_cv(ri, '金额*'))
        if amount <= 0:
            errors.append(f'第{ri}行: 金额必须大于0（当前读到"{_cv(ri, "金额*") or "空"}"）')
            continue
        plan.append({'ri': ri, 'project_no': project_no, 'short_name': short_name,
                     'expected_date': date_str, 'sub_dept': sub_dept, 'dept': dept,
                     'amount': amount, 'notes': _cv(ri, '备注')})

    # ══ 有任何问题 → 整表拒绝（自动更正项仍随成功导入一并提示，不阻断）══════════════
    if errors:
        return ok({
            'rejected': True, 'created': 0, 'corrected': 0, 'errors': errors, 'warnings': warnings,
            'message': (f'导入未执行：发现 {len(errors)} 处问题，已全部列出。'
                        f'请在表格中按提示修正后重新导入（整表全部通过才会写入，不会漏导）。'),
        })

    # ══ 阶段二：全部通过 → 一次性写入（整体事务，任一失败回滚）═══════════════════════
    created = 0
    try:
        with transaction.atomic():
            for p in plan:
                Model.objects.create(
                    project_no=p['project_no'], short_name=p['short_name'],
                    expected_date=p['expected_date'], sub_dept=p['sub_dept'],
                    delivery_dept=p['dept'], amount=p['amount'],
                    notes=p['notes'], created_by=user,
                )
                created += 1
    except Exception as e:
        return ok({
            'rejected': True, 'created': 0, 'corrected': 0,
            'errors': [f'写入阶段发生错误并已回滚：{e}。请检查数据后重试。'], 'warnings': warnings,
            'message': '导入未执行（写入阶段出错，已整体回滚，不会出现半截数据）。',
        })

    return ok({'created': created, 'skipped': 0, 'corrected': corrected,
               'errors': [], 'warnings': warnings})


def _budget_export(request, Model, kind):
    denied = _page_denied(request, 'ar_budget')
    if denied:
        return denied
    qs = _ar_dept_filter(Model.objects.all(), request, dept_field='delivery_dept')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    _today = datetime.date.today()
    _ds, _de = _parse_budget_date_range(request, _today)
    qs = qs.filter(expected_date__gte=_ds, expected_date__lte=_de)
    if qs.count() > 5000:
        return err('导出超过5000行，请缩小筛选范围')
    lbl = _budget_label(kind)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f'{lbl}预算'
    headers = ['项目编号', '项目简称/摘要', f'预计{lbl}日期', '二级部门',
               '交付部门', '金额', '备注', '创建人']
    color = '1B6E35' if kind == 'collection' else 'B25600'
    _header_row(ws, headers, color=color)
    for o in qs.select_related('created_by'):
        ws.append([o.project_no, o.short_name, str(o.expected_date), o.sub_dept,
                   o.delivery_dept, float(o.amount), o.notes,
                   o.created_by.name if o.created_by else ''])
    return _export_response(wb, f'{lbl}预算.xlsx')


@csrf_exempt
@pk_required()
def budget_collection_template(request):
    return _budget_template(request, 'collection')


@csrf_exempt
@pk_required()
def budget_collection_import(request):
    return _budget_import(request, CollectionBudget, 'collection')


@csrf_exempt
@pk_required()
def budget_collection_export(request):
    return _budget_export(request, CollectionBudget, 'collection')


@csrf_exempt
@pk_required()
def budget_payment_template(request):
    return _budget_template(request, 'payment')


@csrf_exempt
@pk_required()
def budget_payment_import(request):
    return _budget_import(request, PaymentBudget, 'payment')


@csrf_exempt
@pk_required()
def budget_payment_export(request):
    return _budget_export(request, PaymentBudget, 'payment')


@csrf_exempt
@pk_required()
def budget_summary(request):
    """Monthly budget vs actual summary for the given range and depts."""
    denied = _page_denied(request, 'ar_budget')
    if denied:
        return denied

    today = datetime.date.today()
    start_date, end_date = _parse_budget_date_range(request, today)

    if request.pk_role == 'super_admin':
        depts = list(DEPARTMENTS)
    else:
        depts = list(request.pk_depts)

    # Consume global active-depts scope (injected by axios interceptor as ?depts=A,B,C)
    raw_depts = request.GET.get('depts', '').strip()
    if raw_depts:
        requested = [d for d in raw_depts.split(',') if d.strip()]
        allowed_set = set(depts)
        active = [d for d in requested if d in allowed_set]
        if active:
            depts = active

    # Single-dept page-level filter
    dept_param = request.GET.get('dept', '').strip()
    if dept_param and dept_param in depts:
        depts = [dept_param]

    # Budget totals
    bc = CollectionBudget.objects.filter(
        expected_date__range=(start_date, end_date),
        delivery_dept__in=depts).aggregate(total=Sum('amount'))
    bp = PaymentBudget.objects.filter(
        expected_date__range=(start_date, end_date),
        delivery_dept__in=depts).aggregate(total=Sum('amount'))

    # Actual AR collections (from ARPayment)
    ac = ARPayment.objects.filter(
        payment_date__range=(start_date, end_date),
        ar_record__delivery_dept__in=depts).aggregate(total=Sum('amount'))

    # Actual AP payments (from installments subtable)
    ap_total = (PaymentInstallment.objects
                .filter(pay_date__range=(start_date, end_date),
                        payment__department__in=depts)
                .aggregate(total=Sum('pay_amount'))['total'] or Decimal('0'))

    budget_coll = bc['total'] or Decimal('0')
    budget_paid = bp['total'] or Decimal('0')
    actual_coll = ac['total'] or Decimal('0')
    actual_paid = ap_total

    # Per-dept breakdown for multi-dept comparison chart
    by_dept_result = []
    if len(depts) > 1:
        for d in depts:
            bc_d = CollectionBudget.objects.filter(
                expected_date__range=(start_date, end_date), delivery_dept=d
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            bp_d = PaymentBudget.objects.filter(
                expected_date__range=(start_date, end_date), delivery_dept=d
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            ac_d = ARPayment.objects.filter(
                payment_date__range=(start_date, end_date), ar_record__delivery_dept=d
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            ap_d = (PaymentInstallment.objects
                    .filter(pay_date__range=(start_date, end_date), payment__department=d)
                    .aggregate(total=Sum('pay_amount'))['total'] or Decimal('0'))
            by_dept_result.append({
                'dept': d,
                'budget_collection': float(bc_d),
                'actual_collection': float(ac_d),
                'budget_payment': float(bp_d),
                'actual_payment': float(ap_d),
            })

    return ok({
        'start_date': str(start_date), 'end_date': str(end_date), 'depts': depts,
        'budget_collection': str(budget_coll),
        'budget_payment': str(budget_paid),
        'actual_collection': str(actual_coll),
        'actual_payment': str(actual_paid),
        'collection_achievement_rate': round(float(actual_coll / budget_coll * 100), 2) if budget_coll else None,
        'payment_achievement_rate': round(float(actual_paid / budget_paid * 100), 2) if budget_paid else None,
        'collection_gap': str(budget_coll - actual_coll),
        'payment_gap': str(budget_paid - actual_paid),
        'has_alert': actual_paid > actual_coll,
        'by_dept': by_dept_result,
    })


@csrf_exempt
@pk_required()
def budget_project_compare(request):
    """项目维度预算对照 — 预算（收/付，按项目简称）与实际（应收回款/排款实付，
    按项目简称）同窗对齐，逐项目展示「计划 vs 实际」全貌。

    入参：date_start/date_end（默认本月）、dept（可选）。
    返回 rows：每个涉及项目一行（收款预算/实际收款/达成率/付款预算/实际付款/
    执行率/净现金计划与实际/状态标签）+ summary 汇总。
    """
    denied = _page_denied(request, 'ar_budget')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)

    today = datetime.date.today()
    start_date, end_date = _parse_budget_date_range(request, today)

    if request.pk_role == 'super_admin':
        depts = list(DEPARTMENTS)
    else:
        depts = list(request.pk_depts)
    raw_depts = request.GET.get('depts', '').strip()
    if raw_depts:
        active = [d for d in raw_depts.split(',') if d.strip() and d in set(depts)]
        if active:
            depts = active
    dept_param = request.GET.get('dept', '').strip()
    if dept_param and dept_param in depts:
        depts = [dept_param]

    rows = {}

    def _row(name):
        return rows.setdefault(name, {
            'project': name, 'dept': '', 'customer': '', 'manager': '',
            'budget_in': Decimal('0'), 'actual_in': Decimal('0'),
            'budget_out': Decimal('0'), 'actual_out': Decimal('0'),
        })

    # 收款预算（按简称）
    for g in (CollectionBudget.objects
              .filter(expected_date__range=(start_date, end_date),
                      delivery_dept__in=depts)
              .exclude(short_name='')
              .values('short_name').annotate(s=Sum('amount'))):
        _row(g['short_name'])['budget_in'] += g['s'] or Decimal('0')

    # 付款预算（按简称）
    for g in (PaymentBudget.objects
              .filter(expected_date__range=(start_date, end_date),
                      delivery_dept__in=depts)
              .exclude(short_name='')
              .values('short_name').annotate(s=Sum('amount'))):
        _row(g['short_name'])['budget_out'] += g['s'] or Decimal('0')

    # 实际收款：应收回款经 项目简称（含预收抵扣——预算达成按应收口径）
    for g in (ARPayment.objects
              .filter(payment_date__range=(start_date, end_date),
                      ar_record__delivery_dept__in=depts,
                      ar_record__project__short_name__isnull=False)
              .exclude(ar_record__project__short_name='')
              .values('ar_record__project__short_name').annotate(s=Sum('amount'))):
        _row(g['ar_record__project__short_name'])['actual_in'] += g['s'] or Decimal('0')

    # 实际付款：排款实付分期经 项目简称
    for g in (PaymentInstallment.objects
              .filter(pay_date__range=(start_date, end_date),
                      payment__department__in=depts)
              .exclude(payment__project_short_name='')
              .values('payment__project_short_name').annotate(s=Sum('pay_amount'))):
        _row(g['payment__project_short_name'])['actual_out'] += g['s'] or Decimal('0')

    if rows:
        for p in ARProject.objects.filter(short_name__in=list(rows.keys())):
            r = rows.get(p.short_name)
            if r is not None and not r['dept']:
                r['dept'] = p.delivery_dept or ''
                r['customer'] = p.customer_name or ''
                r['manager'] = p.project_manager or ''

    def _rate(actual, budget):
        return round(float(actual / budget * 100), 1) if budget else None

    out_rows = []
    for r in rows.values():
        bi, ai, bo, ao = r['budget_in'], r['actual_in'], r['budget_out'], r['actual_out']
        tags = []
        if bi > 0 and ai >= bi:
            tags.append('收款达成')
        elif bi > 0 and ai < bi:
            tags.append('收款滞后')
        elif bi == 0 and ai > 0:
            tags.append('计划外收款')
        if bo > 0 and ao > bo:
            tags.append('付款超预算')
        elif bo == 0 and ao > 0:
            tags.append('计划外付款')
        out_rows.append({
            **{k: str(v) if isinstance(v, Decimal) else v for k, v in r.items()},
            'in_rate': _rate(ai, bi),
            'out_rate': _rate(ao, bo),
            'in_gap': str(bi - ai),
            'out_gap': str(bo - ao),
            'budget_net': str(bi - bo),
            'actual_net': str(ai - ao),
            'tags': tags,
        })
    # 体量大的排前面（预算+实际合计）
    out_rows.sort(key=lambda x: (Decimal(x['budget_in']) + Decimal(x['budget_out'])
                                 + Decimal(x['actual_in']) + Decimal(x['actual_out'])),
                  reverse=True)

    t_bi = sum(Decimal(x['budget_in']) for x in out_rows)
    t_ai = sum(Decimal(x['actual_in']) for x in out_rows)
    t_bo = sum(Decimal(x['budget_out']) for x in out_rows)
    t_ao = sum(Decimal(x['actual_out']) for x in out_rows)
    return ok({
        'start_date': str(start_date), 'end_date': str(end_date),
        'rows': out_rows,
        'summary': {
            'count': len(out_rows),
            'budget_in': str(t_bi), 'actual_in': str(t_ai), 'in_rate': _rate(t_ai, t_bi),
            'budget_out': str(t_bo), 'actual_out': str(t_ao), 'out_rate': _rate(t_ao, t_bo),
            'budget_net': str(t_bi - t_bo), 'actual_net': str(t_ai - t_ao),
            'achieved': sum(1 for x in out_rows if '收款达成' in x['tags']),
            'lagging': sum(1 for x in out_rows if '收款滞后' in x['tags']),
            'over_budget': sum(1 for x in out_rows if '付款超预算' in x['tags']),
            'unplanned': sum(1 for x in out_rows
                             if '计划外收款' in x['tags'] or '计划外付款' in x['tags']),
        },
    })




# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
