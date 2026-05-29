import io
import json
import re
import datetime
import calendar
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Sum, Count, Q, F, Value, Case, When, IntegerField, CharField, Max
from django.db.models.functions import TruncMonth
from django.utils import timezone

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from paikuan.views import (pk_required, ok, err, DEPARTMENTS, VALID_DEPARTMENTS,
                           get_request_perms, apply_ar_view_mask, AR_PROJECT_FIELD_DEFS,
                           AR_RECORD_FIELD_DEFS)
from ar.models import ARProject, ARRecord, ARPayment, CollectionBudget, PaymentBudget
from paikuan.models import Payment

# ── AR page keys (must match PAGE_KEYS in paikuan/views.py) ───────────────────
AR_PAGE_KEYS = ['ar_projects', 'ar_records', 'ar_analytics', 'ar_cashflow', 'ar_budget']

EXAMPLE_ROW_MARKER = '示例-导入前请删除此行'
VALID_CUSTOMER_LEVELS = ['S级', 'A级', 'B级', 'C级', 'D级']
VALID_INVOICE_TYPES = ['专票', '普票', '不开票']


def _match_project_by_short_name(short_name, dept='', allowed_depts=None):
    """Match an ARProject by short_name.

    dept: exact delivery_dept filter (highest priority).
    allowed_depts: list of departments to restrict search (used by import to avoid
                   cross-dept confusion for non-super_admin users).
    Falls back to case-insensitive contains match when exact match yields nothing.
    """
    name = (short_name or '').strip()
    if not name:
        return None
    qs = ARProject.objects.filter(short_name=name)
    if dept:
        qs = qs.filter(delivery_dept=dept)
    elif allowed_depts is not None:
        qs = qs.filter(delivery_dept__in=allowed_depts)
    proj = qs.order_by('-id').first()
    if proj:
        return proj
    # fallback: contains match when users type partially
    qs = ARProject.objects.filter(short_name__icontains=name)
    if dept:
        qs = qs.filter(delivery_dept=dept)
    elif allowed_depts is not None:
        qs = qs.filter(delivery_dept__in=allowed_depts)
    return qs.order_by('-id').first()


def _normalize_date(s):
    """Best-effort normalize a user-typed date string to ISO YYYY-MM-DD.

    Accepts: 2026-01-15, 2026/1/15, 2026.1.15, 2026年1月15日, 26/1/15,
    20260115, datetime/date objects, Excel serial numbers.
    """
    import datetime as _dt
    if s is None:
        return None
    # datetime / date objects (openpyxl can return these)
    if isinstance(s, (_dt.datetime, _dt.date)):
        return s.strftime('%Y-%m-%d')
    # Excel serial date (number of days since 1899-12-30)
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        try:
            base = _dt.date(1899, 12, 30)
            return (base + _dt.timedelta(days=int(s))).strftime('%Y-%m-%d')
        except (OverflowError, ValueError):
            return None
    s = str(s).strip()
    if not s or s.lower() == 'none':
        return None
    # 20260115 → 2026-01-15
    if re.fullmatch(r'\d{8}', s):
        try:
            return f'{s[:4]}-{s[4:6]}-{s[6:]}'
        except ValueError:
            pass
    # Drop chinese unit suffixes / unify separators
    cleaned = (s.replace('/', '-').replace('.', '-')
                .replace('年', '-').replace('月', '-').replace('日', '')
                .replace(' ', '').strip('-'))
    parts = [p for p in cleaned.split('-') if p]
    try:
        if len(parts) >= 3:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            # 2-digit year → 20xx
            if y < 100:
                y += 2000
            _dt.date(y, m, d)  # validate
            return f'{y:04d}-{m:02d}-{d:02d}'
    except (ValueError, TypeError):
        pass
    return None


def _dec(v, default=Decimal('0')):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return default


def _parse_body(request):
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def _ar_dept_filter(qs, request, dept_field='delivery_dept'):
    """Filter queryset by the requesting user's allowed departments.
    Optional ?depts=A,B,C further narrows the set (intersected with pk_depts)."""
    raw = request.GET.get('depts', '').strip()
    requested = [d for d in raw.split(',') if d.strip()] if raw else []

    if request.pk_role == 'super_admin':
        if requested:
            return qs.filter(**{f'{dept_field}__in': requested})
        return qs

    allowed = set(request.pk_depts or [])
    if not allowed:
        return qs.none()
    if requested:
        active = [d for d in requested if d in allowed]
        if active:
            return qs.filter(**{f'{dept_field}__in': active})
    return qs.filter(**{f'{dept_field}__in': request.pk_depts})


def _page_denied(request, page_key):
    """Return error response if user lacks access to a page; None if allowed."""
    if request.pk_role == 'super_admin':
        return None
    from paikuan.views import get_job_perms
    jt = getattr(request, 'pk_job', '') or ''
    if not jt:
        from paikuan.models import PaikuanUser
        u = PaikuanUser.objects.filter(id=request.pk_uid).only('job_title').first()
        jt = u.job_title if u else ''
    perms = get_job_perms(jt)
    if not perms['pages'].get(page_key, True):
        return err('无权访问此模块', 403)
    return None


def _write_denied(request):
    perms = get_request_perms(request)
    if perms is not None and not perms.get('can_create', False):
        return err('无写入权限', 403, 403)
    return None


def _delete_denied(request):
    perms = get_request_perms(request)
    if perms is not None and not perms.get('can_delete', False):
        return err('无删除权限', 403, 403)
    return None


def _dept_denied(request, dept, msg='无权操作此部门'):
    if request.pk_role == 'super_admin':
        return None
    if dept not in request.pk_depts:
        return err(msg, 403, 403)
    return None


def _object_dept_denied(request, obj, dept_field='delivery_dept'):
    return _dept_denied(request, getattr(obj, dept_field, ''), '无权访问')


def _can_ar_view(request, field_key):
    perms = get_request_perms(request)
    if perms is None:
        return True
    return (perms.get('ar_view') or {}).get(field_key, True)


def _ar_field_denied(request, field_key):
    if not _can_ar_view(request, field_key):
        return err('无权访问此字段', 403, 403)
    return None


def _ar_visible_payload(request, data, group, extra=()):
    perms = get_request_perms(request)
    if perms is None:
        return data
    defs = AR_PROJECT_FIELD_DEFS if group == 'project' else AR_RECORD_FIELD_DEFS
    ar_view = perms.get('ar_view') or {}
    cols = set(extra)
    for f in defs:
        if ar_view.get(f['key'], True):
            cols.update(f['cols'])
    return {k: v for k, v in data.items() if k in cols}


def _visible_ar_export_cols(request, columns):
    perms = get_request_perms(request)
    if perms is None:
        return columns
    ar_view = perms.get('ar_view') or {}
    return [col for col in columns if col[0] is None or ar_view.get(col[0], True)]


def _export_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(buf.read(),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    safe = quote(filename, safe='')
    resp['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe}"
    resp['Cache-Control'] = 'no-store'
    return resp


def _header_row(ws, headers, color='1565C0'):
    fill = PatternFill('solid', fgColor=color)
    font = Font(color='FFFFFF', bold=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(horizontal='center')


# ══════════════════════════════════════════════════════════════════════════════
# Projects
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@pk_required()
def projects(request):
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied

    if request.method == 'GET':
        qs = _ar_dept_filter(ARProject.objects.all(), request)
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(contract_name__icontains=q) |
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

        # Customer-level filter (S/A/...)
        level = request.GET.get('customer_level', '').strip()
        if level:
            qs = qs.filter(customer_level=level)
        mode = request.GET.get('invoice_mode', '').strip()
        if mode:
            qs = qs.filter(invoice_mode=mode)

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
        data = _ar_visible_payload(request, _parse_body(request), 'project')
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
        try:
            p = ARProject(
                contract_name=data.get('contract_name', '').strip(),
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
                invoice_mode=data.get('invoice_mode', '全额'),
                invoice_type=data.get('invoice_type', ''),
                tax_rate=_dec(data.get('tax_rate', '0')),
                notes=data.get('notes', '').strip(),
                created_by=user,
            )
            p.save()
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

    if request.method == 'GET':
        d = proj.to_dict()
        agg = proj.ar_records.aggregate(
            record_count=Count('id'), total_outstanding=Sum('outstanding_amount'))
        d['record_count'] = agg['record_count'] or 0
        d['total_outstanding'] = str(agg['total_outstanding'] or 0)
        return ok(apply_ar_view_mask(d, get_request_perms(request), 'project'))

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _ar_visible_payload(request, _parse_body(request), 'project')
        for field in ('contract_name', 'short_name', 'sub_dept', 'business_mode',
                      'customer_level', 'sales_contact', 'project_manager',
                      'has_contract', 'invoice_mode', 'invoice_type', 'notes'):
            if field in data:
                setattr(proj, field, data[field])
        if 'contract_date' in data:
            proj.contract_date = _normalize_date(data['contract_date']) or None
        for field in ('reconciliation_days', 'invoice_wait_days', 'post_invoice_days'):
            if field in data:
                setattr(proj, field, int(data[field] or 0))
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
        proj.save()
        return ok(apply_ar_view_mask(proj.to_dict(), get_request_perms(request), 'project'))

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        proj.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def project_template(request):
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '项目信息'
    headers = ['合同名称*', '项目简称*', '交付部门*', '二级部门', '业务模式',
               '客户等级', '销售对接人*', '项目负责人*', '有无合同',
               '签订日期', '合同对账期(天)', '开票等待期(天)', '票后等待期(天)',
               '开票模式(全额/差额)', '专票/普票/不开票', '税率(如0.06)', '备注']
    _header_row(ws, headers)
    tip_vals = [
        '★必填：合同/项目全称（唯一标识，再次导入同名合同+同一事业部时自动更新，不新增）',
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
        '整数天数，默认0（票后等待期：开票后多少天内完成回款；应收日期 = 运作月月末 + 总账期天数；修改后自动更新已有明细）',
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
               'A级', '张三', '李四', '有', '2026-01-01', 30, 0, 60,
               '全额', '专票', 0.06, '示例备注（此行含"示例"标记，导入时自动跳过）']
    ws.append(example)
    col_widths = [28, 18, 16, 14, 14, 12, 16, 16, 10, 18, 20, 20, 20, 18, 18, 14, 24]
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
    col_map = {h: i + 1 for i, h in enumerate(headers)}

    def _cv(row, name):
        idx = col_map.get(name)
        if idx is None:
            return ''
        v = ws.cell(row, idx).value
        return str(v).strip() if v is not None else ''

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    created = updated = skipped = 0
    errors = []

    for ri in range(2, ws.max_row + 1):
        contract_name = _cv(ri, '合同名称*')
        if not contract_name or EXAMPLE_ROW_MARKER in contract_name or contract_name.startswith('★'):
            skipped += 1
            continue
        dept = _cv(ri, '交付部门*')
        if dept not in VALID_DEPARTMENTS:
            errors.append(f'第{ri}行: 交付部门"{dept}"无效，可选值为：{"/".join(VALID_DEPARTMENTS)}')
            skipped += 1
            continue
        if request.pk_role != 'super_admin':
            allowed = request.pk_depts
            if dept not in allowed:
                errors.append(f'第{ri}行: 无权操作部门"{dept}"，您的授权部门为：{"/".join(allowed)}')
                skipped += 1
                continue
        # ── field-level validation ────────────────────────────────────────────
        customer_level_val = _cv(ri, '客户等级')
        if customer_level_val and customer_level_val not in VALID_CUSTOMER_LEVELS:
            errors.append(f'第{ri}行: 客户等级"{customer_level_val}"无效，应为：{"/".join(VALID_CUSTOMER_LEVELS)}')
            skipped += 1
            continue
        invoice_type_val = _cv(ri, '专票/普票/不开票') or _cv(ri, '专票/普票')
        if invoice_type_val and invoice_type_val not in VALID_INVOICE_TYPES:
            errors.append(f'第{ri}行: 发票类型"{invoice_type_val}"无效，应为：{"/".join(VALID_INVOICE_TYPES)}')
            skipped += 1
            continue
        invoice_mode_val = _cv(ri, '开票模式(全额/差额)') or '全额'
        if invoice_mode_val not in ('全额', '差额'):
            errors.append(f'第{ri}行: 开票模式"{invoice_mode_val}"无效，应为"全额"或"差额"')
            skipped += 1
            continue
        tax_raw = _cv(ri, '税率(如0.06)')
        if tax_raw:
            try:
                tax_val = float(tax_raw)
                if not (0 <= tax_val <= 1):
                    errors.append(f'第{ri}行: 税率"{tax_raw}"超出范围，应在0到1之间（如 0.06 表示6%）')
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                errors.append(f'第{ri}行: 税率"{tax_raw}"格式错误，应填数字（如 0.06）')
                skipped += 1
                continue
        try:
            int_days = lambda col: int(_cv(ri, col) or 0)
            field_vals = dict(
                short_name=_cv(ri, '项目简称*') or _cv(ri, '项目简称'),
                sub_dept=_cv(ri, '二级部门'),
                business_mode=_cv(ri, '业务模式'),
                customer_level=customer_level_val,
                sales_contact=_cv(ri, '销售对接人*'),
                project_manager=_cv(ri, '项目负责人*'),
                has_contract=_cv(ri, '有无合同') or '无',
                contract_date=_normalize_date(
                    _cv(ri, '签订日期') or _cv(ri, '签订日期(YYYY-MM-DD)')
                ) or None,
                reconciliation_days=int_days('合同对账期(天)'),
                invoice_wait_days=int_days('开票等待期(天)'),
                post_invoice_days=int_days('票后等待期(天)'),
                invoice_mode=invoice_mode_val,
                invoice_type=invoice_type_val,
                tax_rate=_dec(tax_raw),
                notes=_cv(ri, '备注'),
            )
            # Upsert: update existing project rather than creating a duplicate.
            # Business key: (contract_name, delivery_dept).
            existing = ARProject.objects.filter(
                contract_name=contract_name, delivery_dept=dept).first()
            if existing:
                for k, v in field_vals.items():
                    setattr(existing, k, v)
                existing.delivery_dept = dept
                existing.save()  # triggers ARProject.post_save signal → updates ARRecord due_dates
                updated += 1
            else:
                p = ARProject(contract_name=contract_name, delivery_dept=dept,
                              created_by=user, **field_vals)
                p.save()
                created += 1
        except Exception as e:
            errors.append(f'第{ri}行: {e}')
            skipped += 1

    return ok({'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors})


@csrf_exempt
@pk_required()
def project_export(request):
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    qs = _ar_dept_filter(ARProject.objects.all(), request)
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(contract_name__icontains=q) | Q(short_name__icontains=q) |
            Q(project_no__icontains=q))

    if qs.count() > 5000:
        return err('导出超过5000行，请缩小筛选范围')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '项目信息'
    columns = _visible_ar_export_cols(request, [
        (None, '项目编号', lambda p: p.project_no),
        ('p_contract_name', '合同名称', lambda p: p.contract_name),
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
    qs = _ar_dept_filter(ARProject.objects.all(), request)
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    total = qs.count()
    shared = qs.filter(is_shared=True).count()

    # Customer level breakdown
    level_rows = qs.values('customer_level').annotate(c=Count('id'))
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
        'shared': shared,
        's_count': s_count,
        'a_count': a_count,
        'level_map': level_map,
        'new_this_month': this_count,
        'new_last_month': last_count,
        'mom_growth': mom,
    })


# ══════════════════════════════════════════════════════════════════════════════
# AR Records
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@pk_required()
def ar_records(request):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied

    if request.method == 'GET':
        today = datetime.date.today()
        # Listing queryset — select_related for efficient to_dict() rendering
        qs = _ar_dept_filter(ARRecord.objects.select_related('project', 'created_by'), request)
        qs = _apply_record_filters(qs, request)
        qs = _apply_record_state_filters(qs, request, today)

        include_payments = request.GET.get('include_payments', '') in ('1', 'true')
        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))

        # Aggregate queryset — plain queryset (no select_related) avoids any
        # accidental extra JOINs and keeps results consistent with the group-summary
        # endpoint which also uses ARRecord.objects.all() as its base.
        qs_agg = _ar_dept_filter(ARRecord.objects.all(), request)
        qs_agg = _apply_record_filters(qs_agg, request)
        qs_agg = _apply_record_state_filters(qs_agg, request, today)

        total = qs_agg.count()
        # 当前筛选全集的金额合计（不止当前页）——支撑"筛选即合计"
        # Only sum outstanding_amount where > 0: matches the table which renders
        # non-positive rows as "—" (settled/overpaid treated identically as 0).
        agg = qs_agg.aggregate(
            est=Sum('estimated_amount'),
            inv=Sum('actual_invoice_amount'),
            tax=Sum('tax_amount'),
            out=Sum('outstanding_amount', filter=Q(outstanding_amount__gt=0)),
        )
        summary = {
            'count': total,
            'estimated': str(agg['est'] or 0),
            'invoiced': str(agg['inv'] or 0),
            'tax': str(agg['tax'] or 0),
            'outstanding': str(agg['out'] or 0),
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
            rows = []
            for r in items:
                d = r.to_dict(today=today)
                d['payments'] = pay_map.get(r.id, [])
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
            extra=('project_id', 'operation_year', 'operation_month'))
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
        year = int(data.get('operation_year', 0) or 0)
        month = int(data.get('operation_month', 0) or 0)
        if not (year and 1 <= month <= 12):
            return err('运作年月无效')
        from paikuan.models import PaikuanUser
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        try:
            rec = ARRecord(
                project=proj,
                operation_year=year,
                operation_month=month,
                estimated_amount=_dec(data.get('estimated_amount', 0)),
                actual_invoice_amount=_dec(data['actual_invoice_amount']) if data.get('actual_invoice_amount') not in (None, '') else None,
                tax_amount=_dec(data['tax_amount']) if data.get('tax_amount') not in (None, '') else None,
                invoice_date=_normalize_date(data.get('invoice_date')) or None,
                reconciliation_date=_normalize_date(data.get('reconciliation_date')) or None,
                notes=data.get('notes', '').strip(),
                created_by=user,
            )
            rec.save()
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

    today = datetime.date.today()

    if request.method == 'GET':
        return ok(apply_ar_view_mask(rec.to_dict(today=today, include_payments=True),
                                     get_request_perms(request), 'record'))

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _ar_visible_payload(request, _parse_body(request), 'record')
        for field in ('estimated_amount',):
            if field in data:
                setattr(rec, field, _dec(data[field]))
        if 'actual_invoice_amount' in data:
            rec.actual_invoice_amount = _dec(data['actual_invoice_amount']) if data['actual_invoice_amount'] not in (None, '') else None
        if 'account_diff_adjustment' in data:
            rec.account_diff_adjustment = _dec(data['account_diff_adjustment'])
        if 'tax_amount' in data:
            rec.tax_amount = _dec(data['tax_amount']) if data['tax_amount'] not in (None, '') else None
        if 'invoice_date' in data:
            rec.invoice_date = _normalize_date(data['invoice_date']) or None
        if 'reconciliation_date' in data:
            rec.reconciliation_date = _normalize_date(data['reconciliation_date']) or None
        if 'notes' in data:
            rec.notes = data['notes'].strip()
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
    headers = ['项目简称*', '运作年*', '运作月*', '预估上账金额', '实际开票金额',
               '税额(差额模式手填)', '开票日期', '账实差额调整', '回款金额', '回款时间', '备注']
    _header_row(ws, headers, color='1B6E35')
    tip_vals = [
        '★必填：填写项目台账中的"项目简称"（精确匹配，简称是应收明细与项目台账的唯一桥梁，必须先在项目台账建档）',
        '★必填：4位整数，如 2026（每个项目每个月每天都可有多条开票/回款记录，多次导入即追加新行）',
        '★必填：1-12 的整数（同一项目同一年月可存在多行，代表当月多批次上账）',
        '选填：当月预计上账金额（元）；计算公式：未回款 = 上账金额 + 账实差额调整 - 全部回款之和',
        '选填：实际开票金额（元）；全额模式下税额自动计算；对账时以此确认是否已对账',
        '选填：差额模式时手动填写税额（元）；全额模式：税额=开票金额÷(1+税率)×税率，自动算，无需填',
        '选填：格式 2026-01-15 / 2026/1/15 / 2026年1月15日 均可',
        '选填：账实差额调整（元，可正可负）；未回款 = 上账金额 + 此值 - 已回款；用于修正账面差异',
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
    ws.append([EXAMPLE_ROW_MARKER, 2026, 1, 100000, 100000, '', '2026-01-15', 0, 30000, '2026-01-20',
               '示例（此行含"示例"标记，导入时自动跳过）'])
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 22
    return _export_response(wb, '应收账款明细导入模板.xlsx')


@csrf_exempt
@pk_required()
def ar_record_import(request):
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
    col_map = {h: i + 1 for i, h in enumerate(headers)}

    # Header aliases for backward compatibility / user-friendly variants
    _ALIASES = {
        '开票日期': ['开票日期', '开票日期(YYYY-MM-DD)', '开票日期*'],
        '回款时间': ['回款时间', '回款时间(YYYY-MM-DD)', '回款日期'],
        '税额(差额模式手填)': ['税额(差额模式手填)', '税额'],
        '预估上账金额': ['预估上账金额', '预估金额', '上账金额'],
        '实际开票金额': ['实际开票金额', '开票金额'],
        '账实差额调整': ['账实差额调整', '账实差额'],
        '回款金额': ['回款金额'],
        '项目简称*': ['项目简称*', '项目简称'],
        '运作年*': ['运作年*', '运作年'],
        '运作月*': ['运作月*', '运作月'],
        '备注': ['备注'],
    }

    def _resolve_idx(name):
        for h in _ALIASES.get(name, [name]):
            if h in col_map:
                return col_map[h]
        return None

    def _cv_raw(row, name):
        idx = _resolve_idx(name)
        if idx is None:
            return None
        return ws.cell(row, idx).value

    def _cv(row, name):
        v = _cv_raw(row, name)
        return str(v).strip() if v is not None else ''

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    created = skipped = updated = 0
    errors = []

    for ri in range(2, ws.max_row + 1):
        short_name = _cv(ri, '项目简称*')
        if not short_name or EXAMPLE_ROW_MARKER in short_name or short_name.startswith('★'):
            skipped += 1
            continue
        search_depts = None if request.pk_role == 'super_admin' else request.pk_depts
        proj = _match_project_by_short_name(short_name, allowed_depts=search_depts)
        if not proj:
            errors.append(f'第{ri}行: 项目简称"{short_name}"未匹配到项目')
            skipped += 1
            continue
        if request.pk_role != 'super_admin':
            allowed = request.pk_depts
            if proj.delivery_dept not in allowed:
                errors.append(f'第{ri}行: 无权操作部门"{proj.delivery_dept}"')
                skipped += 1
                continue
        year = int(_cv(ri, '运作年*') or 0)
        month = int(_cv(ri, '运作月*') or 0)
        if not (year and 1 <= month <= 12):
            errors.append(f'第{ri}行: 运作年月无效')
            skipped += 1
            continue
        try:
            # 同一项目同月可有多条记录；每行导入一律新建，避免合并不同业务批次
            rec = ARRecord(project=proj, operation_year=year, operation_month=month,
                           created_by=user)
            created_new = True
            est = _cv(ri, '预估上账金额')
            if est and _can_ar_view(request, 'r_estimated_amount'):
                rec.estimated_amount = _dec(est)
            actual = _cv(ri, '实际开票金额')
            if _can_ar_view(request, 'r_actual_invoice_amount'):
                rec.actual_invoice_amount = _dec(actual) if actual else None
            tax_raw = _cv(ri, '税额(差额模式手填)')
            if _can_ar_view(request, 'r_tax_amount'):
                rec.tax_amount = _dec(tax_raw) if tax_raw else None
            inv_date = _normalize_date(_cv_raw(ri, '开票日期'))
            if _can_ar_view(request, 'r_invoice_date'):
                rec.invoice_date = inv_date or None
            diff_adj = _cv(ri, '账实差额调整')
            if diff_adj and _can_ar_view(request, 'r_account_diff'):
                rec.account_diff_adjustment = _dec(diff_adj)
            notes = _cv(ri, '备注')
            if _can_ar_view(request, 'r_notes'):
                rec.notes = notes
            rec.save()
            pay_amount = _cv(ri, '回款金额')
            pay_date = _normalize_date(_cv_raw(ri, '回款时间'))
            if pay_amount and pay_date:
                amt = _dec(pay_amount)
                if amt > 0:
                    # Idempotency: skip if a payment with same date+amount already exists
                    dup = rec.payments.filter(payment_date=pay_date, amount=amt).exists()
                    if not dup:
                        max_no = rec.payments.aggregate(m=Max('payment_no')).get('m') or 0
                        ARPayment.objects.create(
                            ar_record=rec,
                            payment_no=max_no + 1,
                            amount=amt,
                            payment_date=pay_date,
                            notes='导入回款'
                        )
                        rec.recompute_derived()
            if created_new:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f'第{ri}行: {e}')
            skipped += 1

    recomputed = created + updated
    tip = '导入后系统已按现规则自动重算未收回金额（不沿用历史手工未收回金额）。'
    return ok({'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors,
               'recomputed': recomputed, 'tip': tip})


@csrf_exempt
@pk_required()
def ar_record_export(request):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    today = datetime.date.today()
    qs = _ar_dept_filter(ARRecord.objects.select_related('project'), request)
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    year = request.GET.get('year', '').strip()
    if year:
        qs = qs.filter(operation_year=int(year))
    month = request.GET.get('month', '').strip()
    if month:
        qs = qs.filter(operation_month=int(month))
    if qs.count() > 5000:
        return err('导出超过5000行，请缩小筛选范围')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '应收账款明细'
    columns = _visible_ar_export_cols(request, [
        (None, '项目编号', lambda rec, st: rec.project.project_no),
        ('p_short_name', '项目简称', lambda rec, st: rec.project.short_name),
        ('p_contract_name', '合同名称', lambda rec, st: rec.project.contract_name),
        ('p_delivery_dept', '交付部门', lambda rec, st: rec.delivery_dept),
        ('p_project_manager', '项目负责人', lambda rec, st: rec.project.project_manager),
        ('p_sales_contact', '销售对接人', lambda rec, st: rec.project.sales_contact),
        ('p_account_period', '总账期(天)', lambda rec, st: rec.project.total_days),
        (None, '运作年', lambda rec, st: rec.operation_year),
        (None, '运作月', lambda rec, st: rec.operation_month),
        ('r_estimated_amount', '预估上账金额', lambda rec, st: float(rec.estimated_amount)),
        ('r_actual_invoice_amount', '实际开票金额',
         lambda rec, st: float(rec.actual_invoice_amount) if rec.actual_invoice_amount is not None else ''),
        ('r_tax_amount', '税额', lambda rec, st: float(rec.tax_amount) if rec.tax_amount is not None else ''),
        ('r_invoice_date', '开票日期', lambda rec, st: str(rec.invoice_date) if rec.invoice_date else ''),
        ('p_invoice_config', '开票模式', lambda rec, st: rec.project.invoice_mode),
        ('r_account_diff', '账实差额调整', lambda rec, st: float(rec.account_diff_adjustment)),
        ('r_outstanding', '未回款金额', lambda rec, st: float(rec.outstanding_amount)),
        ('r_due_date', '应收日期', lambda rec, st: str(rec.due_date) if rec.due_date else ''),
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


def _apply_record_filters(qs, request):
    """Shared dimension filters for AR records (used by list + kpi)."""
    project_id = request.GET.get('project_id', '').strip()
    if project_id:
        qs = qs.filter(project_id=int(project_id))
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    year = request.GET.get('year', '').strip()
    if year:
        qs = qs.filter(operation_year=int(year))
    month = request.GET.get('month', '').strip()
    if month:
        qs = qs.filter(operation_month=int(month))
    manager = request.GET.get('manager', '').strip()
    if manager:
        qs = qs.filter(project__project_manager__icontains=manager)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(project__short_name__icontains=q) |
            Q(project__contract_name__icontains=q) |
            Q(project__project_no__icontains=q))
    return qs


def _apply_record_state_filters(qs, request, today=None):
    """Status / invoice / reconciliation / due-date filters for AR records.

    Used by the list view, the export view and the group-summary view so the
    same filter semantics apply everywhere. NOT used by the KPI endpoint, which
    computes its own status breakdown from the unfiltered (by-state) set.
    """
    if today is None:
        today = datetime.date.today()
    eomonth_today = datetime.date(today.year, today.month,
                                  calendar.monthrange(today.year, today.month)[1])

    status = request.GET.get('status', '').strip()
    if status == 'overdue':
        qs = qs.filter(outstanding_amount__gt=0, due_date__lt=today)
    elif status == 'current':
        qs = qs.filter(outstanding_amount__gt=0, due_date__gte=today,
                       due_date__lte=eomonth_today)
    elif status == 'not_due':
        qs = qs.filter(outstanding_amount__gt=0, due_date__gt=eomonth_today)
    elif status == 'settled':
        qs = qs.filter(outstanding_amount__lte=0)
    elif status == 'outstanding':
        qs = qs.filter(outstanding_amount__gt=0)

    inv_status = request.GET.get('invoice_status', '').strip()
    if inv_status == '未开票':
        qs = qs.filter(actual_invoice_amount__isnull=True)
    elif inv_status == '已结清':
        qs = qs.filter(outstanding_amount__lte=0, actual_invoice_amount__isnull=False)
    elif inv_status == '已开票':
        qs = qs.filter(actual_invoice_amount__isnull=False, outstanding_amount__gt=0)

    recon_status = request.GET.get('reconciliation_status', '').strip()
    if recon_status == '已对账':
        qs = qs.filter(Q(reconciliation_date__isnull=False) | Q(actual_invoice_amount__isnull=False))
    elif recon_status == '未对账':
        qs = qs.filter(reconciliation_date__isnull=True, actual_invoice_amount__isnull=True)

    # 责任状态（responsibility phase）— 按责任归属阶段过滤，与明细列的
    # post_invoice_status 责任链一致。逾期/等待中的细分依赖日期运算，这里只过滤到
    # 责任方所属阶段（settled / 对账阶段 / 开票阶段 / 票后回款阶段），可纯 DB 表达。
    responsibility = request.GET.get('responsibility', '').strip()
    if responsibility:
        no_inv = Q(project__invoice_type='不开票')
        if responsibility == 'settled':
            qs = qs.filter(outstanding_amount__lte=0)
        elif responsibility == 'post':
            # 票后/回款阶段（销售对接人责任）
            qs = qs.filter(
                Q(outstanding_amount__gt=0) & (
                    (no_inv & Q(reconciliation_date__isnull=False)) |
                    (~no_inv & Q(invoice_date__isnull=False))
                )
            )
        elif responsibility == 'invoice':
            # 待开票阶段（开票人责任）
            qs = qs.filter(
                Q(outstanding_amount__gt=0) & ~no_inv & Q(invoice_date__isnull=True) &
                (Q(reconciliation_date__isnull=False) | Q(actual_invoice_amount__isnull=False))
            )
        elif responsibility == 'recon':
            # 对账阶段（非销售责任）
            qs = qs.filter(
                Q(outstanding_amount__gt=0) & (
                    (no_inv & Q(reconciliation_date__isnull=True)) |
                    (~no_inv & Q(invoice_date__isnull=True) &
                     Q(reconciliation_date__isnull=True) & Q(actual_invoice_amount__isnull=True))
                )
            )

    due_start = request.GET.get('due_start', '').strip()
    due_end = request.GET.get('due_end', '').strip()
    if due_start:
        qs = qs.filter(due_date__gte=due_start)
    if due_end:
        qs = qs.filter(due_date__lte=due_end)
    return qs


@csrf_exempt
@pk_required()
def ar_records_kpi(request):
    """Per-tracking completion KPIs for the current filter (对账/开票/回款)."""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    today = datetime.date.today()
    qs = _apply_record_filters(
        _ar_dept_filter(ARRecord.objects.all(), request), request)

    total = qs.count()

    # Reconciliation: 已对账 vs 未对账
    recon_done = qs.filter(Q(reconciliation_date__isnull=False) | Q(actual_invoice_amount__isnull=False)).count()
    recon_pending = total - recon_done

    # Invoice: 已开票 vs 未开票（含金额）
    inv_done_qs = qs.filter(actual_invoice_amount__isnull=False)
    inv_done = inv_done_qs.count()
    inv_pending = total - inv_done
    # 未开票预估金额：尚未开票记录的预估上账金额合计
    inv_pending_amount = (qs.filter(actual_invoice_amount__isnull=True)
                          .aggregate(s=Sum('estimated_amount'))['s'] or 0)
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
    qs = _ar_dept_filter(qs, request, dept_field='ar_record__delivery_dept')
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
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(ar_record__project__short_name__icontains=q) |
            Q(ar_record__project__contract_name__icontains=q) |
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
        'notes': p.notes,
        'project_no': proj.project_no,
        'short_name': proj.short_name,
        'delivery_dept': rec.delivery_dept,
        'operation_year': rec.operation_year,
        'operation_month': rec.operation_month,
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
    headers = ['回款日期', '回款金额', '项目编号', '项目简称', '交付部门',
               '运作年', '运作月', '回款序号', '备注']
    _header_row(ws, headers, color='1B6E35')
    for p in qs:
        r = _payment_ledger_row(p)
        ws.append([r['payment_date'], float(p.amount), r['project_no'], r['short_name'],
                   r['delivery_dept'], r['operation_year'], r['operation_month'],
                   r['payment_no'], r['notes']])
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
    qs = _ar_dept_filter(ARRecord.objects.all(), request)
    qs = _apply_record_filters(qs, request)
    qs = _apply_record_state_filters(qs, request, today)

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
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        amount = _dec(data.get('amount', 0))
        if amount <= 0:
            return err('回款金额必须大于0')
        pay_date = _normalize_date(data.get('payment_date'))
        if not pay_date:
            return err('回款日期无效')
        try:
            with transaction.atomic():
                last = rec.payments.select_for_update().order_by('-payment_no').first()
                next_no = (last.payment_no + 1) if last else 1
                pay = ARPayment.objects.create(
                    ar_record=rec,
                    payment_no=next_no,
                    amount=amount,
                    payment_date=pay_date,
                    notes=data.get('notes', '').strip(),
                )
        except ValidationError as e:
            return err(str(e.message if hasattr(e, 'message') else e), 400)
        return ok(pay.to_dict())

    return err('Method not allowed', 405)


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
    denied = _ar_field_denied(request, 'r_payments')
    if denied:
        return denied

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        if 'amount' in data:
            amount = _dec(data['amount'])
            if amount <= 0:
                return err('回款金额必须大于0')
            pay.amount = amount
        if 'payment_date' in data:
            pay.payment_date = _normalize_date(data['payment_date']) or pay.payment_date
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
        ARRecord.objects.filter(outstanding_amount__gt=0), request)
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

    year = int(request.GET.get('year', datetime.date.today().year))
    qs = _ar_dept_filter(ARRecord.objects.filter(operation_year=year), request)
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
        ARRecord.objects.filter(outstanding_amount__gt=0), request)
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    by_project = (qs.values('project_id', 'project__project_no', 'project__short_name',
                             'project__contract_name', 'delivery_dept')
                  .annotate(total_outstanding=Sum('outstanding_amount'))
                  .order_by('-total_outstanding')[:n])

    result = []
    for r in by_project:
        result.append({
            'project_id': r['project_id'],
            'project_no': r['project__project_no'],
            'short_name': r['project__short_name'] or r['project__contract_name'],
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
    qs = _ar_dept_filter(ARRecord.objects.all(), request)
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

    year = int(request.GET.get('year', datetime.date.today().year))
    qs = _ar_dept_filter(ARRecord.objects.filter(operation_year=year), request)
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)

    rows = (qs.values('project__project_manager')
              .annotate(
                  estimated=Sum('estimated_amount'),
                  outstanding=Sum('outstanding_amount'),
                  total_paid=Sum('payments__amount'),
                  project_count=Count('project_id', distinct=True),
              )
              .order_by('-outstanding'))

    result = []
    for r in rows:
        pm = r['project__project_manager'] or '（未填写）'
        estimated = float(r['estimated'] or 0)
        outstanding = float(r['outstanding'] or 0)
        total_paid = float(r['total_paid'] or 0)
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
        start_year = int(request.GET.get('start_year', today.year))
        start_month = int(request.GET.get('start_month', 1))
        end_year = int(request.GET.get('end_year', today.year))
        end_month = int(request.GET.get('end_month', today.month))
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

    # AR collections by month across all requested depts
    ar_coll = (ARPayment.objects
               .filter(payment_date__gte=start_date, payment_date__lte=end_date,
                       ar_record__delivery_dept__in=depts)
               .annotate(ym=TruncMonth('payment_date'))
               .values('ym', 'ar_record__delivery_dept')
               .annotate(collected=Sum('amount')))
    coll_map = defaultdict(lambda: defaultdict(Decimal))
    for row in ar_coll:
        ym = row['ym'].strftime('%Y-%m')
        dept = row['ar_record__delivery_dept']
        coll_map[dept][ym] += row['collected'] or Decimal('0')

    # AP payments (3 slots) by month
    paid_map = defaultdict(lambda: defaultdict(Decimal))
    for slot in ['pay1', 'pay2', 'pay3']:
        date_field = f'{slot}_date'
        amount_field = f'{slot}_amount'
        qs_slot = (Payment.objects
                   .filter(**{f'{date_field}__isnull': False,
                               f'{date_field}__gte': start_date,
                               f'{date_field}__lte': end_date,
                               'department__in': depts})
                   .annotate(ym=TruncMonth(date_field))
                   .values('ym', 'department')
                   .annotate(paid=Sum(amount_field)))
        for row in qs_slot:
            ym = row['ym'].strftime('%Y-%m')
            dept = row['department']
            paid_map[dept][ym] += row['paid'] or Decimal('0')

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
    total_bcoll = defaultdict(Decimal)
    total_bpaid = defaultdict(Decimal)
    has_alert = False

    for dept in depts:
        series_coll = [float(coll_map[dept].get(ym, 0)) for ym in month_keys]
        series_paid = [float(paid_map[dept].get(ym, 0)) for ym in month_keys]
        series_bcoll = [float(budget_coll_map[dept].get(ym, 0)) for ym in month_keys]
        series_bpaid = [float(budget_paid_map[dept].get(ym, 0)) for ym in month_keys]
        alert_months = [month_keys[i] for i in range(len(month_keys))
                        if series_paid[i] > series_coll[i] > 0]
        if alert_months:
            has_alert = True
        by_dept.append({
            'dept': dept,
            'collected': series_coll,
            'paid': series_paid,
            'budget_collection': series_bcoll,
            'budget_payment': series_bpaid,
            'alert_months': alert_months,
        })
        for i, ym in enumerate(month_keys):
            total_coll[ym] += coll_map[dept].get(ym, Decimal('0'))
            total_paid[ym] += paid_map[dept].get(ym, Decimal('0'))
            total_bcoll[ym] += budget_coll_map[dept].get(ym, Decimal('0'))
            total_bpaid[ym] += budget_paid_map[dept].get(ym, Decimal('0'))

    total_alert = [ym for ym in month_keys
                   if float(total_paid.get(ym, 0)) > float(total_coll.get(ym, 0)) > 0]
    if total_alert:
        has_alert = True

    collected_arr = [float(total_coll.get(ym, 0)) for ym in month_keys]
    paid_arr = [float(total_paid.get(ym, 0)) for ym in month_keys]
    net_arr = [round(collected_arr[i] - paid_arr[i], 2) for i in range(len(month_keys))]
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
        year = request.GET.get('year', '').strip()
        if year:
            qs = qs.filter(expected_date__year=int(year))
        month = request.GET.get('month', '').strip()
        if month:
            qs = qs.filter(expected_date__month=int(month))
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
            return err('预计日期无效')
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
    headers = ['项目编号(可选)', '项目简称/摘要*', f'预计{lbl}日期(YYYY-MM-DD)*',
               '二级部门', '交付部门', '金额*', '备注']
    color = '1B6E35' if kind == 'collection' else 'B25600'
    _header_row(ws, headers, color=color)
    ws.append([EXAMPLE_ROW_MARKER, '示例项目A', '2026-06-15', '华南区',
               '劳务事业部', 100000, '示例备注'])
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20
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

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    created = skipped = 0
    errors = []
    for ri in range(2, ws.max_row + 1):
        short_name = _cv(ri, '项目简称/摘要*')
        if not short_name or EXAMPLE_ROW_MARKER in short_name:
            skipped += 1
            continue
        date_str = _normalize_date(_cv(ri, f'预计{lbl}日期(YYYY-MM-DD)*'))
        if not date_str:
            errors.append(f'第{ri}行: 预计日期无效')
            skipped += 1
            continue
        dept = _cv(ri, '交付部门')
        # Auto-derive dept from project when the column is left blank
        if not dept and short_name:
            search_depts = None if request.pk_role == 'super_admin' else request.pk_depts
            _pre = _match_project_by_short_name(short_name, allowed_depts=search_depts)
            if _pre:
                dept = _pre.delivery_dept
        if dept and dept not in VALID_DEPARTMENTS:
            errors.append(f'第{ri}行: 无效交付部门"{dept}"')
            skipped += 1
            continue
        if request.pk_role != 'super_admin' and dept not in request.pk_depts:
            errors.append(f'第{ri}行: 无权操作部门"{dept}"')
            skipped += 1
            continue
        amount = _dec(_cv(ri, '金额*'))
        if amount <= 0:
            errors.append(f'第{ri}行: 金额必须大于0')
            skipped += 1
            continue
        try:
            proj = _match_project_by_short_name(short_name, dept)
            Model.objects.create(
                project_no=(proj.project_no if proj else _cv(ri, '项目编号(可选)')),
                short_name=short_name,
                expected_date=date_str,
                sub_dept=(proj.sub_dept if proj else _cv(ri, '二级部门')),
                delivery_dept=dept,
                amount=amount,
                notes=_cv(ri, '备注'),
                created_by=user,
            )
            created += 1
        except Exception as e:
            errors.append(f'第{ri}行: {e}')
            skipped += 1
    return ok({'created': created, 'skipped': skipped, 'errors': errors})


def _budget_export(request, Model, kind):
    denied = _page_denied(request, 'ar_budget')
    if denied:
        return denied
    qs = _ar_dept_filter(Model.objects.all(), request, dept_field='delivery_dept')
    dept = request.GET.get('dept', '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    year = request.GET.get('year', '').strip()
    if year:
        qs = qs.filter(expected_date__year=int(year))
    month = request.GET.get('month', '').strip()
    if month:
        qs = qs.filter(expected_date__month=int(month))
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
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    start_date = datetime.date(year, month, 1)
    end_date = datetime.date(year, month, calendar.monthrange(year, month)[1])

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

    # Actual AP payments
    ap_total = Decimal('0')
    for slot in ['pay1', 'pay2', 'pay3']:
        df = f'{slot}_date'
        af = f'{slot}_amount'
        r = Payment.objects.filter(
            **{f'{df}__range': (start_date, end_date), 'department__in': depts}
        ).aggregate(total=Sum(af))
        ap_total += r['total'] or Decimal('0')

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
            ap_d = Decimal('0')
            for slot in ['pay1', 'pay2', 'pay3']:
                r = Payment.objects.filter(
                    **{f'{slot}_date__range': (start_date, end_date), 'department': d}
                ).aggregate(total=Sum(f'{slot}_amount'))
                ap_d += r['total'] or Decimal('0')
            by_dept_result.append({
                'dept': d,
                'budget_collection': float(bc_d),
                'actual_collection': float(ac_d),
                'budget_payment': float(bp_d),
                'actual_payment': float(ap_d),
            })

    return ok({
        'year': year, 'month': month, 'depts': depts,
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
