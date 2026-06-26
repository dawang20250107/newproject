"""项目台账（projects）业务域视图：项目列表/详情/批量删除、模板·导入导出、统计、
草稿项目完善与提升，以及项目侧的合同挂接、客户清理等助手。共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403
from paikuan.list_filters import build_filter_q, resolve_sort

# ══════════════════════════════════════════════════════════════════════════════
# Projects
# ══════════════════════════════════════════════════════════════════════════════

# Excel 风格「列头筛选 + 排序」白名单：仅登记 ARProject 上的真实 DB 列（跳过
# 计算/聚合列）。col 为 ORM lookup。未注册字段/类型不符的运算符一律静默忽略。
PROJECT_FILTER_REGISTRY = {
    'customer_name':   {'type': 'text',   'col': 'customer_name'},
    'short_name':      {'type': 'text',   'col': 'short_name'},
    'project_no':      {'type': 'text',   'col': 'project_no'},
    'delivery_dept':   {'type': 'enum',   'col': 'delivery_dept'},
    'sub_dept':        {'type': 'text',   'col': 'sub_dept'},
    # business_mode 在模型中为自由文本、无固定选项 → 用文本「包含/等于」筛选
    'business_mode':   {'type': 'text',   'col': 'business_mode'},
    'customer_level':  {'type': 'enum',   'col': 'customer_level'},
    'project_manager': {'type': 'text',   'col': 'project_manager'},
    'sales_contact':   {'type': 'text',   'col': 'sales_contact'},
    'invoice_mode':    {'type': 'enum',   'col': 'invoice_mode'},
    'status':          {'type': 'enum',   'col': 'status'},
    'contract_date':   {'type': 'date',   'col': 'contract_date'},
    'tax_rate':        {'type': 'number', 'col': 'tax_rate'},
    'has_contract':    {'type': 'enum',   'col': 'has_contract'},
    'notes':           {'type': 'text',   'col': 'notes'},
}


def _apply_project_list_filters(qs, request):
    """项目台账列表筛选（q/dept/manager/is_shared/is_draft/customer_level/invoice_mode）。
    列表 GET 与批量删除「全选筛选集」共用，保证删除范围与所见列表一致。"""
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(customer_name__icontains=q) |
            Q(short_name__icontains=q) |
            Q(project_no__icontains=q) |
            Q(project_manager__icontains=q) |
            Q(sales_contact__icontains=q)
        )
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    manager = request.GET.get('manager', '').strip()
    if manager:
        qs = qs.filter(project_manager__icontains=manager)
    is_shared = request.GET.get('is_shared', '').strip()
    if is_shared in ('true', '1'):
        qs = qs.filter(is_shared=True)
    elif is_shared in ('false', '0'):
        qs = qs.filter(is_shared=False)
    is_draft = request.GET.get('is_draft', '').strip()
    if is_draft in ('true', '1'):
        qs = qs.filter(is_draft=True)
    elif is_draft in ('false', '0'):
        qs = qs.filter(is_draft=False)
    level = request.GET.get('customer_level', '').strip()
    if level:
        qs = qs.filter(customer_level=level)
    mode = request.GET.get('invoice_mode', '').strip()
    if mode:
        qs = qs.filter(invoice_mode=mode)
    status = request.GET.get('status', '').strip()
    if status:
        qs = qs.filter(status=status)
    # Excel 风格列头筛选（白名单驱动）；与列表 GET / 批量删除共用此口径。
    fq, fq_distinct = build_filter_q(request.GET.get('filters', ''), PROJECT_FILTER_REGISTRY)
    if fq:
        qs = qs.filter(fq)
        if fq_distinct:
            qs = qs.distinct()
    return qs


@csrf_exempt
@pk_required()
def projects(request):
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied

    if request.method == 'GET':
        qs = _apply_project_list_filters(
            _ar_dept_filter(ARProject.objects.all(), request, shared_field='is_shared'),
            request)

        # Excel 风格列头排序（白名单驱动）；未指定/非法字段回退模型默认排序。
        sort_by = resolve_sort(request.GET.get('sort'), request.GET.get('order'), PROJECT_FILTER_REGISTRY)
        if sort_by:
            qs = qs.order_by(sort_by)

        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(100, max(1, int(request.GET.get('size', 50) or 50)))
        total = qs.count()
        items = list(qs.select_related('created_by')[(page - 1) * size: page * size])

        perms = get_request_perms(request)
        rows = [apply_ar_view_mask(p.to_dict(), perms, 'project') for p in items]
        return ok({'items': rows, 'total': total, 'page': page, 'size': size})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _ar_visible_payload(request, _parse_body(request), 'project',
                                   extra=('customer_id', 'contract_ids'))
        dept = data.get('delivery_dept', '')
        if dept not in VALID_DEPARTMENTS:
            return err(f'无效交付部门: {dept}')
        if dept == '集团总部':
            return err('集团总部无项目，不允许新增项目台账')
        denied = _dept_denied(request, dept, '无权操作此部门')
        if denied:
            return denied
        from paikuan.models import PaikuanUser
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        csd, csd_err = _parse_cycle_start_day(data.get('cycle_start_day'))
        if csd_err:
            return err(csd_err)
        try:
            p = ARProject(
                customer_name=data.get('customer_name', '').strip(),
                short_name=data.get('short_name', '').strip(),
                delivery_dept=dept,
                sub_dept=data.get('sub_dept', '').strip(),
                business_mode=data.get('business_mode', '').strip(),
                customer_level=data.get('customer_level', '').strip(),
                sales_contact=data.get('sales_contact', '').strip(),
                project_manager=data.get('project_manager', '').strip(),
                has_contract=data.get('has_contract', '无'),
                contract_date=_normalize_date(data.get('contract_date')) or None,
                reconciliation_days=int(data.get('reconciliation_days', 0) or 0),
                invoice_wait_days=int(data.get('invoice_wait_days', 0) or 0),
                post_invoice_days=int(data.get('post_invoice_days', 0) or 0),
                cycle_start_day=csd,
                invoice_mode=data.get('invoice_mode', '全额'),
                invoice_type=data.get('invoice_type', ''),
                tax_rate=_dec(data.get('tax_rate', '0')),
                notes=data.get('notes', '').strip(),
                created_by=user,
            )
            cid = data.get('customer_id')
            if cid:
                p.customer = Customer.objects.filter(pk=cid).first()
            p.save()
            if 'contract_ids' in data:
                _sync_project_contracts(p, data['contract_ids'], request)
        except Exception as e:
            return err(str(e))
        return ok(apply_ar_view_mask(p.to_dict(), get_request_perms(request), 'project'))

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def project_detail(request, pk):
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    try:
        proj = ARProject.objects.select_related('created_by').get(pk=pk)
    except ARProject.DoesNotExist:
        return err('项目不存在', 404)
    # dept access
    if request.pk_role != 'super_admin':
        allowed = request.pk_depts
        if proj.delivery_dept not in allowed:
            return err('无权访问', 403)
        perms = get_request_perms(request)
        if perms and perms.get('ar_shared_only') and not proj.is_shared:
            return err('无权访问', 403)

    if request.method == 'GET':
        d = proj.to_dict()
        agg = proj.ar_records.aggregate(
            record_count=Count('id'), total_outstanding=Sum('outstanding_amount'))
        d['record_count'] = agg['record_count'] or 0
        d['total_outstanding'] = str(agg['total_outstanding'] or 0)
        d['contracts'] = _project_contracts_list(proj)
        return ok(apply_ar_view_mask(d, get_request_perms(request), 'project'))

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _ar_visible_payload(request, _parse_body(request), 'project',
                                   extra=('customer_id', 'contract_ids', 'is_draft', 'status'))
        for field in ('customer_name', 'short_name', 'sub_dept',
                      'business_mode', 'customer_level', 'sales_contact', 'project_manager',
                      'has_contract', 'invoice_mode', 'invoice_type', 'notes'):
            if field in data:
                setattr(proj, field, data[field])
        if 'status' in data:
            st = (data['status'] or '').strip()
            if st not in dict(ARProject.STATUS_CHOICES):
                return err(f'无效项目状态「{st}」，可选：运作中/中断/结束')
            proj.status = st
        if 'contract_date' in data:
            proj.contract_date = _normalize_date(data['contract_date']) or None
        for field in ('reconciliation_days', 'invoice_wait_days', 'post_invoice_days'):
            if field in data:
                setattr(proj, field, int(data[field] or 0))
        if 'cycle_start_day' in data:
            csd, csd_err = _parse_cycle_start_day(data['cycle_start_day'])
            if csd_err:
                return err(csd_err)
            proj.cycle_start_day = csd
        if 'tax_rate' in data:
            proj.tax_rate = _dec(data['tax_rate'])
        if 'delivery_dept' in data:
            dept = data['delivery_dept']
            if dept not in VALID_DEPARTMENTS:
                return err(f'无效交付部门: {dept}')
            denied = _dept_denied(request, dept, '无权操作目标部门')
            if denied:
                return denied
            proj.delivery_dept = dept
        if 'is_draft' in data:
            proj.is_draft = bool(data['is_draft'])
        if 'customer_id' in data:
            cid = data.get('customer_id')
            orig_cid = proj.customer_id   # 进入本分支前尚未改动，即数据库原值
            typed = (data.get('customer_name') or '').strip() if 'customer_name' in data else None
            if cid:
                try:
                    new_cid = int(cid)
                    cust = Customer.objects.get(pk=new_cid)
                    if new_cid != orig_cid:
                        # 用户在「关联客户」里改选了不同的客户实体 → 以实体为准
                        proj.customer = cust
                        proj.customer_name = cust.name
                    elif typed and typed != cust.name:
                        # 关联客户未变但修改了客户名称文本 → 以文本为准，
                        # 置空实体由 save() 的 _autolink_customer 按新名称(+部门)重新挂接
                        proj.customer = None
                    else:
                        proj.customer = cust
                        proj.customer_name = cust.name
                except (Customer.DoesNotExist, ValueError, TypeError):
                    pass
            else:
                proj.customer = None
        proj.save()
        if 'contract_ids' in data:
            _sync_project_contracts(proj, data['contract_ids'], request)
        out = proj.to_dict()
        out['contracts'] = _project_contracts_list(proj)
        return ok(apply_ar_view_mask(out, get_request_perms(request), 'project'))

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        cust_id = proj.customer_id
        proj.delete()
        purged = _purge_orphan_customers([cust_id] if cust_id else [])
        return ok({'deleted': pk, 'purged_customers': purged})

    return err('Method not allowed', 405)


def _purge_orphan_customers(cust_ids):
    """项目删除后的客户名单同步：客户名单由项目台账派生，项目删尽即随之移除。
    仅清理「名下 0 项目且无合同关联」的客户，避免误删仍被合同引用的客户实体。"""
    ids = [i for i in (cust_ids or []) if i]
    if not ids:
        return 0
    qs = (Customer.objects.filter(pk__in=ids)
          .annotate(_np=Count('projects', distinct=True),
                    _nc=Count('contract_links', distinct=True))
          .filter(_np=0, _nc=0))
    n = qs.count()
    if n:
        qs.delete()
    return n


@csrf_exempt
@pk_required()
def projects_bulk_delete(request):
    """批量删除项目（级联其应收明细/回款）。两种模式：
      - 显式选择：body {ids:[int,...]}
      - 选择全部筛选集：body {all:true} + 查询串里的 q/dept/customer_level/... 与列表同口径
    始终受部门作用域与删除权限约束；单次上限 5000 条，防误删全库。"""
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _delete_denied(request)
    if denied:
        return denied

    body = _parse_body(request)
    base = _ar_dept_filter(ARProject.objects.all(), request, shared_field='is_shared')

    if body.get('all'):
        # 与列表 GET 完全相同的筛选口径（走查询串）
        qs = _apply_project_list_filters(base, request)
    else:
        ids = body.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return err('请提供要删除的项目 ids')
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
    del_ids = list(qs.values_list('id', flat=True))
    cust_ids = list(qs.exclude(customer_id__isnull=True)
                    .values_list('customer_id', flat=True).distinct())
    ARProject.objects.filter(pk__in=del_ids).delete()  # 级联删除应收明细/回款
    purged = _purge_orphan_customers(cust_ids)  # 客户名单随项目台账同步收敛
    return ok({'deleted': len(del_ids), 'purged_customers': purged})


@csrf_exempt
@pk_required()
def project_template(request):
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '项目信息'
    headers = ['客户名称*', '项目简称*', '交付部门*', '二级部门', '业务模式',
               '客户等级', '销售对接人*', '项目负责人*', '有无合同',
               '签订日期', '合同对账期(天)', '开票等待期(天)', '票后等待期(天)',
               '对账周期起始日(1-28)',
               '开票模式(全额/差额)', '专票/普票/不开票', '税率(如0.06)', '备注']
    _header_row(ws, headers)
    tip_vals = [
        '★必填：客户名称/往来单位全称（即客户公司名；再次导入同名客户+同一事业部时自动更新，不新增；预收录入选此项目时自动带出为往来单位）',
        f'★必填：项目简称，须在事业部内唯一！应收明细、收款预算导入时均以此简称匹配项目，简称为关键桥梁',
        f'★必填：可选值：{"、".join(VALID_DEPARTMENTS)}（每个事业部每天新增客户，每位客户可有多个不同项目）',
        '选填：华南区/华北区等，可空',
        '选填：劳务外包/运输/供应链等，自由填写',
        f'选填：{"/".join(VALID_CUSTOMER_LEVELS)}，默认可空',
        '★必填：销售对接人姓名（与项目负责人不同时自动标记为共享业务）',
        '★必填：项目负责人姓名（应收分析可按项目负责人维度聚合）',
        '"有"或"无"，默认无',
        '选填：格式 2026-01-15 / 2026/1/15 / 2026年1月15日 均可',
        '整数天数，默认0（总账期 = 合同对账期 + 开票等待期 + 票后等待期）',
        '整数天数，默认0（同上，三项之和即为应收日期的延迟天数）',
        '整数天数，默认0（票后等待期：开票后多少天内完成回款；应收日期 = 对账周期结束日 + 总账期天数；修改后自动更新已有明细）',
        '选填：1~28，默认1=自然月（月初到月末）。如月结周期为每月15日到下月14日则填 15；'
        '应收到期 = 运作日期所在账期的结束日 + 总账期天数，修改后已有明细到期日自动重算',
        '"全额"或"差额"（全额：税额自动计算=开票金额/(1+税率)×税率；差额：手填税额）',
        f'{"/".join(VALID_INVOICE_TYPES)}；选"不开票"时税率自动置0',
        '选填：如 0.06 表示6%，范围 0~1；选"不开票"时留空或填0',
        '选填备注',
    ]
    ws.append(tip_vals)
    tip_row = ws.max_row
    tip_fill = PatternFill('solid', fgColor='FFF9E6')
    tip_font = Font(italic=True, color='8B6914', size=9)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(tip_row, c)
        cell.fill = tip_fill
        cell.font = tip_font
        cell.alignment = Alignment(wrap_text=True)
    example = [EXAMPLE_ROW_MARKER, '物流外包A', '劳务事业部', '华南区', '劳务外包',
               'A级', '张三', '李四', '有', '2026-01-01', 30, 0, 60, 1,
               '全额', '专票', 0.06, '示例备注（此行含"示例"标记，导入时自动跳过）']
    ws.append(example)
    col_widths = [28, 18, 16, 14, 14, 12, 16, 16, 10, 18, 20, 20, 20, 20, 18, 18, 14, 24]
    for col, w in enumerate(col_widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w
    ws.row_dimensions[tip_row].height = 60
    return _export_response(wb, '项目信息导入模板.xlsx')


@csrf_exempt
@pk_required()
def project_import(request):
    denied = _page_denied(request, 'ar_projects')
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
    # 表头规范化：去掉 *、括号注释与空格，使「模板表头(带*)」与「导出表头(不带*)」
    # 双向匹配——否则导出→编辑→再导入会因表头不一致而整表静默跳过。
    col_map = {_norm_header(h): i + 1 for i, h in enumerate(headers)}

    def _cv(row, *names):
        """按规范化表头取值，支持传多个候选别名（任一命中即返回）。"""
        for name in names:
            idx = col_map.get(_norm_header(name))
            if idx is None:
                continue
            v = ws.cell(row, idx).value
            if v is not None and str(v).strip():
                return str(v).strip()
        return ''

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    errors = []
    plan = []   # 通过校验、待写入的行：{ri, customer_name, dept, short_name_val, field_vals}

    # ══ 阶段一：逐行校验（不写库）。示例/提示/空行静默忽略，问题行收集错误 ══════════
    for ri in range(2, ws.max_row + 1):
        customer_name = _cv(ri, '客户名称', '客户名称*', '合同名称', '合同名称*')
        short_name_val = _cv(ri, '项目简称', '项目简称*')
        dept = _cv(ri, '交付部门', '交付部门*')
        # 提示行/示例行：静默忽略（不计入、不报错）
        if (EXAMPLE_ROW_MARKER in customer_name or customer_name.startswith('★')
                or EXAMPLE_ROW_MARKER in short_name_val or short_name_val.startswith('★')):
            continue
        # 客户名称缺失时回退用项目简称（很多用户只填项目简称）；二者皆空才算空行
        if not customer_name:
            customer_name = short_name_val
        if not customer_name:
            # 整行为空 → 静默忽略；否则明确报错，避免「无声跳过」
            if not any(_cv(ri, h) for h in (
                    '交付部门', '销售对接人', '项目负责人', '业务模式')):
                continue
            errors.append(f'第{ri}行: 缺少「客户名称」或「项目简称」，无法识别项目，请补填后重新导入')
            continue
        if dept not in VALID_DEPARTMENTS:
            errors.append(f'第{ri}行: 交付部门"{dept}"无效，可选值为：{"/".join(VALID_DEPARTMENTS)}')
            continue
        if request.pk_role != 'super_admin':
            allowed = request.pk_depts
            if dept not in allowed:
                errors.append(f'第{ri}行: 无权操作部门"{dept}"，您的授权部门为：{"/".join(allowed)}')
                continue
        # ── field-level validation ────────────────────────────────────────────
        customer_level_val = _cv(ri, '客户等级')
        if customer_level_val and customer_level_val not in VALID_CUSTOMER_LEVELS:
            errors.append(f'第{ri}行: 客户等级"{customer_level_val}"无效，应为：{"/".join(VALID_CUSTOMER_LEVELS)}')
            continue
        invoice_type_val = _cv(ri, '专票/普票/不开票', '专票/普票', '发票类型')
        if invoice_type_val and invoice_type_val not in VALID_INVOICE_TYPES:
            errors.append(f'第{ri}行: 发票类型"{invoice_type_val}"无效，应为：{"/".join(VALID_INVOICE_TYPES)}')
            continue
        invoice_mode_val = _cv(ri, '开票模式(全额/差额)') or '全额'
        if invoice_mode_val not in ('全额', '差额'):
            errors.append(f'第{ri}行: 开票模式"{invoice_mode_val}"无效，应为"全额"或"差额"')
            continue
        tax_raw = _cv(ri, '税率(如0.06)')
        if tax_raw:
            try:
                tax_val = float(tax_raw)
                if not (0 <= tax_val <= 1):
                    errors.append(f'第{ri}行: 税率"{tax_raw}"超出范围，应在0到1之间（如 0.06 表示6%）')
                    continue
            except (ValueError, TypeError):
                errors.append(f'第{ri}行: 税率"{tax_raw}"格式错误，应填数字（如 0.06）')
                continue
        try:
            int_days = lambda col: int(_cv(ri, col) or 0)
        except (ValueError, TypeError):
            errors.append(f'第{ri}行: 账期天数应为整数（合同对账期/开票等待期/票后等待期）')
            continue
        field_vals = dict(
            short_name=short_name_val,
            sub_dept=_cv(ri, '二级部门'),
            business_mode=_cv(ri, '业务模式'),
            customer_level=customer_level_val,
            sales_contact=_cv(ri, '销售对接人', '销售对接人*'),
            project_manager=_cv(ri, '项目负责人', '项目负责人*'),
            has_contract=_cv(ri, '有无合同') or '无',
            contract_date=_normalize_date(
                _cv(ri, '签订日期') or _cv(ri, '签订日期(YYYY-MM-DD)')
            ) or None,
            reconciliation_days=int_days('合同对账期(天)'),
            invoice_wait_days=int_days('开票等待期(天)'),
            post_invoice_days=int_days('票后等待期(天)') or int_days('结算等待期(天)'),
            invoice_mode=invoice_mode_val,
            invoice_type=invoice_type_val,
            notes=_cv(ri, '备注'),
        )
        # 对账周期起始日（_norm_header 去括号注释后列名为「对账周期起始日」）
        csd_raw = _cv(ri, '对账周期起始日(1-28)', '对账周期起始日')
        if csd_raw:
            csd_val, csd_err = _parse_cycle_start_day(csd_raw)
            if csd_err:
                errors.append(f'第{ri}行: {csd_err}')
                continue
            field_vals['cycle_start_day'] = csd_val
        # 仅在明确填写税率时才写入，避免留空时把现有项目的税率清零
        if tax_raw:
            field_vals['tax_rate'] = _dec(tax_raw)
        plan.append({'ri': ri, 'customer_name': customer_name, 'dept': dept,
                     'short_name_val': short_name_val, 'field_vals': field_vals})

    # ══ 有任何问题 → 整表拒绝，不写入（要么修正后重导，要么照提示逐条改）═══════════
    if errors:
        return ok({
            'rejected': True, 'created': 0, 'updated': 0, 'errors': errors,
            'message': (f'导入未执行：发现 {len(errors)} 处问题，已全部列出。'
                        f'请在表格中按提示修正后重新导入（整表全部通过才会写入，不会漏导）。'),
        })

    # ══ 阶段二：全部通过 → 一次性写入（整体事务，任一失败回滚）═══════════════════════
    created = updated = 0
    try:
        with transaction.atomic():
            for p in plan:
                # Upsert: 业务主键「项目简称 + 交付部门」（简称为空才回退合同名）
                if p['short_name_val']:
                    existing = ARProject.objects.filter(
                        short_name=p['short_name_val'], delivery_dept=p['dept']).first()
                else:
                    existing = ARProject.objects.filter(
                        customer_name=p['customer_name'], delivery_dept=p['dept']).first()
                if existing:
                    for k, v in p['field_vals'].items():
                        setattr(existing, k, v)
                    existing.delivery_dept = p['dept']
                    existing.save()  # triggers post_save signal → updates ARRecord due_dates
                    updated += 1
                else:
                    pr = ARProject(customer_name=p['customer_name'], delivery_dept=p['dept'],
                                   created_by=user, **p['field_vals'])
                    pr.save()
                    created += 1
    except Exception as e:
        return ok({
            'rejected': True, 'created': 0, 'updated': 0,
            'errors': [f'写入阶段发生错误并已回滚：{e}。请检查数据后重试。'],
            'message': '导入未执行（写入阶段出错，已整体回滚，不会出现半截数据）。',
        })

    return ok({'created': created, 'updated': updated, 'skipped': 0, 'errors': []})


_PROJECT_AI_SYS = (
    '你是企业项目台账的数据质检助手。下面是一批待导入的项目记录（已通过基础格式校验）。'
    '请只挑出"疑似有问题"的行：客户名称/项目简称像乱码/测试数据/占位符；'
    '同一客户存在明显重复（简称、部门、销售对接人相同）；税率或账期天数明显异常。'
    '严格只返回 JSON 数组，每个元素形如 '
    '{"row":行号,"field":"字段名","issue":"问题简述","suggestion":"修正建议(可空)","severity":"high|medium|low"}。'
    '没有发现问题就返回 []。不要输出 JSON 以外的任何文字。'
)

_PROJECT_COLUMNS = [
    {'key': 'customer_name', 'label': '客户名称'},
    {'key': 'short_name', 'label': '项目简称'},
    {'key': 'dept', 'label': '交付部门'},
    {'key': 'sales_contact', 'label': '销售对接人'},
    {'key': 'project_manager', 'label': '项目负责人'},
    {'key': 'business_mode', 'label': '业务模式'},
    {'key': 'has_contract', 'label': '有无合同'},
]


@csrf_exempt
@pk_required()
def project_import_precheck(request):
    """项目台账导入预检：规则校验 + AI 复核。只读不落库。
    用户确认后由前端重新提交文件到 /import 写库（AR 通用「文件留存+重提」模式）。"""
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _page_denied(request, 'ar_projects')
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

    def _cv(row, *names):
        for name in names:
            idx = col_map.get(_norm_header(name))
            if idx is None:
                continue
            v = ws.cell(row, idx).value
            if v is not None and str(v).strip():
                return str(v).strip()
        return ''

    report_rows, ai_input = [], []

    for ri in range(2, ws.max_row + 1):
        customer_name = _cv(ri, '客户名称', '客户名称*', '合同名称', '合同名称*')
        short_name_val = _cv(ri, '项目简称', '项目简称*')
        dept = _cv(ri, '交付部门', '交付部门*')
        if (EXAMPLE_ROW_MARKER in customer_name or customer_name.startswith('★')
                or EXAMPLE_ROW_MARKER in short_name_val or short_name_val.startswith('★')):
            continue
        if not customer_name:
            customer_name = short_name_val
        if not customer_name:
            if not any(_cv(ri, h) for h in ('交付部门', '销售对接人', '项目负责人', '业务模式')):
                continue
        rule_issue = None
        if not customer_name:
            rule_issue = '缺少「客户名称」或「项目简称」，无法识别项目'
        elif dept and dept not in VALID_DEPARTMENTS:
            rule_issue = f'交付部门"{dept}"无效，可选值为：{"/".join(VALID_DEPARTMENTS)}'
        elif request.pk_role != 'super_admin' and dept and dept not in request.pk_depts:
            rule_issue = f'无权操作部门"{dept}"'
        else:
            customer_level_val = _cv(ri, '客户等级')
            if customer_level_val and customer_level_val not in VALID_CUSTOMER_LEVELS:
                rule_issue = f'客户等级"{customer_level_val}"无效，应为：{"/".join(VALID_CUSTOMER_LEVELS)}'
            else:
                invoice_type_val = _cv(ri, '专票/普票/不开票', '专票/普票', '发票类型')
                if invoice_type_val and invoice_type_val not in VALID_INVOICE_TYPES:
                    rule_issue = f'发票类型"{invoice_type_val}"无效，应为：{"/".join(VALID_INVOICE_TYPES)}'

        data = {'customer_name': customer_name, 'short_name': short_name_val, 'dept': dept,
                'sales_contact': _cv(ri, '销售对接人', '销售对接人*'),
                'project_manager': _cv(ri, '项目负责人', '项目负责人*'),
                'business_mode': _cv(ri, '业务模式'), 'has_contract': _cv(ri, '有无合同') or '无'}
        report_rows.append({'row': ri, 'data': data, 'ruleIssue': rule_issue, 'warn': None, 'ai': []})
        if not rule_issue:
            ai_input.append({'row': ri, 'customer_name': customer_name, 'short_name': short_name_val,
                             'dept': dept, 'sales_contact': data['sales_contact'],
                             'project_manager': data['project_manager']})

    by_row = {}
    for fnd in _ar_ai_review(ai_input, _PROJECT_AI_SYS):
        by_row.setdefault(fnd['row'], []).append(fnd)
    for rr in report_rows:
        rr['ai'] = by_row.get(rr['row'], [])

    return ok(_ar_precheck_report(report_rows, _PROJECT_COLUMNS))


@csrf_exempt
@pk_required()
def project_export(request):
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    qs = _ar_dept_filter(ARProject.objects.all(), request, shared_field='is_shared')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(customer_name__icontains=q) | Q(short_name__icontains=q) |
            Q(project_no__icontains=q))

    # 列头筛选 + 排序：与列表 GET 同口径，使导出与所见筛选/排序结果一致。
    fq, fq_distinct = build_filter_q(request.GET.get('filters', ''), PROJECT_FILTER_REGISTRY)
    if fq:
        qs = qs.filter(fq)
        if fq_distinct:
            qs = qs.distinct()
    _sort_by = resolve_sort(request.GET.get('sort'), request.GET.get('order'), PROJECT_FILTER_REGISTRY)
    if _sort_by:
        qs = qs.order_by(_sort_by)

    if qs.count() > 5000:
        return err('导出超过5000行，请缩小筛选范围')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '项目信息'
    columns = _visible_ar_export_cols(request, [
        (None, '项目编号', lambda p: p.project_no),
        ('p_contract_name', '客户名称', lambda p: p.customer_name),
        ('p_short_name', '项目简称', lambda p: p.short_name),
        ('p_delivery_dept', '交付部门', lambda p: p.delivery_dept),
        ('p_sub_dept', '二级部门', lambda p: p.sub_dept),
        ('p_business_mode', '业务模式', lambda p: p.business_mode),
        ('p_customer_level', '客户等级', lambda p: p.customer_level),
        ('p_sales_contact', '销售对接人', lambda p: p.sales_contact),
        ('p_project_manager', '项目负责人', lambda p: p.project_manager),
        ('p_sales_contact', '共享业务', lambda p: '是' if p.is_shared else '否'),
        ('p_has_contract', '有无合同', lambda p: p.has_contract),
        ('p_contract_date', '签订日期', lambda p: str(p.contract_date) if p.contract_date else ''),
        ('p_account_period', '合同对账期(天)', lambda p: p.reconciliation_days),
        ('p_account_period', '开票等待期(天)', lambda p: p.invoice_wait_days),
        ('p_account_period', '票后等待期(天)', lambda p: p.post_invoice_days),
        ('p_account_period', '总账期(天)', lambda p: p.total_days),
        ('p_account_period', '对账周期起始日', lambda p: p.cycle_start_day),
        ('p_invoice_config', '开票模式', lambda p: p.invoice_mode),
        ('p_invoice_config', '专票/普票', lambda p: p.invoice_type),
        ('p_invoice_config', '税率', lambda p: str(p.tax_rate)),
        ('p_notes', '备注', lambda p: p.notes),
    ])
    _header_row(ws, [header for _, header, _ in columns])
    for p in qs:
        ws.append([getter(p) for _, _, getter in columns])
    return _export_response(wb, '项目信息.xlsx')


@csrf_exempt
@pk_required()
def project_stats(request):
    """KPI strip for 项目台账: 项目总数 / S·A 级客户 / 共享业务 / 本月新签环比."""
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    qs = _ar_dept_filter(ARProject.objects.all(), request, shared_field='is_shared')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    total = qs.count()
    draft_count = qs.filter(is_draft=True).count()

    # 运作中项目：S/A级客户数和共享业务数均以运作中项目为准
    running_qs = qs.filter(status='运作中')
    running_count = running_qs.count()
    shared = running_qs.filter(is_shared=True).count()

    # Customer level breakdown（仅运作中）
    level_rows = running_qs.values('customer_level').annotate(c=Count('id'))
    level_map = {(r['customer_level'] or '未分级'): r['c'] for r in level_rows}
    s_count = level_map.get('S级', 0) + level_map.get('S', 0)
    a_count = level_map.get('A级', 0) + level_map.get('A', 0)

    # Month-over-month new signings by contract_date
    today = datetime.date.today()
    this_start = datetime.date(today.year, today.month, 1)
    if today.month == 1:
        last_start = datetime.date(today.year - 1, 12, 1)
    else:
        last_start = datetime.date(today.year, today.month - 1, 1)
    this_count = qs.filter(contract_date__gte=this_start, contract_date__lte=today).count()
    last_end = this_start - datetime.timedelta(days=1)
    last_count = qs.filter(contract_date__gte=last_start, contract_date__lte=last_end).count()
    if last_count:
        mom = round((this_count - last_count) / last_count * 100, 1)
    else:
        mom = None  # no baseline

    return ok({
        'total': total,
        'running_count': running_count,
        'shared': shared,
        'draft_count': draft_count,
        's_count': s_count,
        'a_count': a_count,
        'level_map': level_map,
        'new_this_month': this_count,
        'new_last_month': last_count,
        'mom_growth': mom,
    })


# 草稿项目（待完善）
# ──────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def project_drafts(request):
    """GET /ar/projects/drafts  —  列出所有 is_draft=True 的项目，供人工完善。"""
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)

    qs = _ar_dept_filter(ARProject.objects.filter(is_draft=True), request)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(short_name__icontains=q) | Q(customer_name__icontains=q))
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    page = max(1, int(request.GET.get('page', 1) or 1))
    size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
    total = qs.count()
    perms = get_request_perms(request)
    rows = [apply_ar_view_mask(p.to_dict(), perms, 'project')
            for p in qs.order_by('-id')[(page - 1) * size: page * size]]
    return ok({'items': rows, 'total': total, 'page': page, 'size': size})


@csrf_exempt
@pk_required()
def project_drafts_promote(request):
    """POST /ar/projects/drafts/promote  —  把待完善草稿「转正」为正式项目并同步客户。

    草稿是早期应收导入「找不到项目时自动新建」遗留的占位项目（新版已停用自动建草稿）。
    转正：把信息齐全（有交付部门）的草稿 is_draft 置 False，保存即按 (客户名+部门)
    自动挂接/正名客户——既保留应收数据、又把无部门客户收编进正式客户名单。
    交付部门为空的草稿无法自动判定归属，列出供人工到台账补全部门后再转。
    preview=1 只返回数量分布，不改动。
    """
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    denied = _write_denied(request)
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)

    base = _ar_dept_filter(ARProject.objects.filter(is_draft=True), request)
    total = base.count()
    ready = base.exclude(delivery_dept='')          # 有部门 → 可转正
    need_dept = list(base.filter(delivery_dept='')   # 无部门 → 需人工补
                     .values_list('short_name', flat=True)[:50])

    data = _parse_body(request)
    if request.GET.get('preview') or data.get('preview'):
        return ok({'total': total, 'ready': ready.count(), 'need_dept': len(need_dept)})

    promoted = 0
    with transaction.atomic():
        for p in ready:
            p.is_draft = False
            p.save()     # 触发 _autolink_customer：按 (客户名+部门) 挂客户
            promoted += 1

    msg = f'已转正 {promoted} 个草稿为正式项目并同步客户' if promoted else '没有可直接转正的草稿'
    if need_dept:
        msg += f'；另有 {len(need_dept)} 个草稿缺「交付部门」无法自动转正，请到项目台账补部门后再转（或删除）'
    return ok({'promoted': promoted, 'need_dept_count': len(need_dept),
               'need_dept_samples': need_dept[:10], 'message': msg})




# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
