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
from django.db.models import Sum, Count, Q, F, Value, Case, When, IntegerField, CharField, Max, Min
from django.db.models.functions import TruncMonth
from django.utils import timezone

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from paikuan.views import (pk_required, ok, err, DEPARTMENTS, VALID_DEPARTMENTS,
                           get_request_perms, apply_ar_view_mask, AR_PROJECT_FIELD_DEFS,
                           AR_RECORD_FIELD_DEFS, AR_ADVANCE_FIELD_DEFS)
from ar.models import (ARProject, ARRecord, ARPayment, CollectionBudget, PaymentBudget,
                       AdvanceRecord, AdvanceWriteoff)
from paikuan.models import Payment

# ── AR page keys (must match PAGE_KEYS in paikuan/views.py) ───────────────────
AR_PAGE_KEYS = ['ar_projects', 'ar_records', 'ar_advance', 'ar_analytics', 'ar_cashflow', 'ar_budget']

ADVANCE_DIRECTIONS = ['预收', '预付']

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


def _ar_dept_filter(qs, request, dept_field='delivery_dept', shared_field=None):
    """Filter queryset by the requesting user's allowed departments.
    Optional ?depts=A,B,C further narrows the set (intersected with pk_depts).
    When shared_field is provided and the user has ar_shared_only, restricts to
    shared projects only (shared_field=True)."""
    raw = request.GET.get('depts', '').strip()
    requested = [d for d in raw.split(',') if d.strip()] if raw else []

    if request.pk_role == 'super_admin':
        if requested:
            qs = qs.filter(**{f'{dept_field}__in': requested})
        return qs

    allowed = set(request.pk_depts or [])
    if not allowed:
        return qs.none()
    if requested:
        active = [d for d in requested if d in allowed]
        if active:
            qs = qs.filter(**{f'{dept_field}__in': active})
        else:
            qs = qs.filter(**{f'{dept_field}__in': request.pk_depts})
    else:
        qs = qs.filter(**{f'{dept_field}__in': request.pk_depts})

    if shared_field:
        from paikuan.views import get_request_perms
        perms = get_request_perms(request)
        if perms and perms.get('ar_shared_only'):
            qs = qs.filter(**{shared_field: True})
    return qs


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


_AR_PAYLOAD_DEFS_BY_GROUP = {
    'project': AR_PROJECT_FIELD_DEFS,
    'record': AR_RECORD_FIELD_DEFS,
    'advance': AR_ADVANCE_FIELD_DEFS,
}


def _ar_visible_payload(request, data, group, extra=()):
    perms = get_request_perms(request)
    if perms is None:
        return data
    defs = _AR_PAYLOAD_DEFS_BY_GROUP.get(group, AR_RECORD_FIELD_DEFS)
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
        qs = _ar_dept_filter(ARProject.objects.all(), request, shared_field='is_shared')
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
        perms = get_request_perms(request)
        if perms and perms.get('ar_shared_only') and not proj.is_shared:
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
                post_invoice_days=int_days('票后等待期(天)') or int_days('结算等待期(天)'),
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
    qs = _ar_dept_filter(ARProject.objects.all(), request, shared_field='is_shared')
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
    qs = _ar_dept_filter(ARProject.objects.all(), request, shared_field='is_shared')
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

        # 当前筛选全集的金额合计（不止当前页）——支撑"筛选即合计"。
        # 重要：筛选含 payments 关联（回款日期/含未结清）时 qs_agg 带 JOIN，直接
        # aggregate 会把每条记录的金额按其回款笔数重复累加。先取去重后的记录 id，
        # 再在无 JOIN 的基表上聚合金额；回款金额单独在 ARPayment 上聚合，避免互相放大。
        all_record_ids = list(qs_agg.order_by().values_list('id', flat=True).distinct())
        total = len(all_record_ids)
        base = ARRecord.objects.filter(id__in=all_record_ids)
        # Only sum outstanding_amount where > 0: matches the table which renders
        # non-positive rows as "—" (settled/overpaid treated identically as 0).
        agg = base.aggregate(
            est=Sum('estimated_amount'),
            inv=Sum('actual_invoice_amount'),
            tax=Sum('tax_amount'),
            out=Sum('outstanding_amount', filter=Q(outstanding_amount__gt=0)),
            adj=Sum('account_diff_adjustment'),
        )
        collected = (ARPayment.objects.filter(ar_record_id__in=all_record_ids)
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
        # 周窗口（周一 ~ 周日）
        wk_start = ref_date - datetime.timedelta(days=ref_date.weekday())
        wk_end = wk_start + datetime.timedelta(days=6)
        # 周标签随基准日联动：基准周==今天所在周时叫"本周"，否则叫"该周"
        today_wk_start = today - datetime.timedelta(days=today.weekday())
        week_label = '本周' if wk_start == today_wk_start else '该周'

        # 应收：按 due_date 落在窗口内的记录预估金额求和（null due_date 自动排除）
        # 当期应收：due_date 落在基准月内
        month_curr_est = (base.filter(due_date__gte=mo_start, due_date__lte=mo_end)
                          .aggregate(s=Sum('estimated_amount'))['s'] or 0)
        # 逾期应收：due_date 早于基准月且仍有未收余额，取 outstanding_amount 之和
        month_overdue_est = (base.filter(due_date__lt=mo_start, outstanding_amount__gt=0)
                             .aggregate(s=Sum('outstanding_amount'))['s'] or 0)
        week_est = (base.filter(due_date__gte=wk_start, due_date__lte=wk_end)
                    .aggregate(s=Sum('estimated_amount'))['s'] or 0)

        # 已收：按 payment_date 落在窗口内，限当前筛选记录集
        # 当期已收：回款记录所属的 AR 明细到期日 >= 基准月首日（当期或未来到期）
        # 逾期已收：回款记录所属的 AR 明细到期日 <  基准月首日（逾期后补收）
        # 两者之和 = 旧的 month_collected（本月全部实收）
        pay_in_set = ARPayment.objects.filter(ar_record_id__in=all_record_ids)
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

        summary = {
            'count': total,
            'estimated': str(agg['est'] or 0),
            'invoiced': str(agg['inv'] or 0),
            'tax': str(agg['tax'] or 0),
            'outstanding': str(agg['out'] or 0),
            'adj': str(agg['adj'] or 0),
            'collected': str(collected),
            'month_curr_est': str(month_curr_est),
            'month_curr_collected': str(month_curr_collected),
            'month_overdue_est': str(month_overdue_est),
            'month_overdue_collected': str(month_overdue_collected),
            'week_est': str(week_est),
            'week_collected': str(week_collected),
            'ref_date': ref_date.isoformat(),
            'ref_month': f'{ref_date.year}年{ref_date.month}月',
            'ref_week': f'{wk_start.month}/{wk_start.day}~{wk_end.month}/{wk_end.day}',
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
    qs = _ar_dept_filter(ARRecord.objects.select_related('project'), request,
                         shared_field='project__is_shared')
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
    is_shared = request.GET.get('is_shared', '').strip()
    if is_shared in ('1', 'true'):
        qs = qs.filter(project__is_shared=True)
    elif is_shared in ('0', 'false'):
        qs = qs.filter(project__is_shared=False)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(project__short_name__icontains=q) |
            Q(project__contract_name__icontains=q) |
            Q(project__project_no__icontains=q) |
            Q(project__project_manager__icontains=q))
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
    # 与 ARRecord.invoice_status 属性保持一致：已结清（outstanding<=0）优先级最高，
    # 因此「未开票」必须排除已结清记录（未开票 = 未开票 且 仍有未收余额）。
    if inv_status == '未开票':
        qs = qs.filter(actual_invoice_amount__isnull=True, outstanding_amount__gt=0)
    elif inv_status == '已结清':
        qs = qs.filter(outstanding_amount__lte=0)
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

    # 回款筛选：pay_status='unpaid' 纯无回款；pay_include_unpaid=1 与日期区间做 OR
    # （"3月回款 + 含未结清"→传 pay_start/pay_end + pay_include_unpaid=1）
    pay_status = request.GET.get('pay_status', '').strip()
    pay_include_unpaid = request.GET.get('pay_include_unpaid', '') in ('1', 'true')
    pay_start = request.GET.get('pay_start', '').strip()
    pay_end = request.GET.get('pay_end', '').strip()
    has_date = bool(pay_start or pay_end)

    if has_date:
        date_q = Q()
        if pay_start:
            date_q &= Q(payments__payment_date__gte=pay_start)
        if pay_end:
            date_q &= Q(payments__payment_date__lte=pay_end)
        if pay_include_unpaid:
            qs = qs.filter(date_q | Q(outstanding_amount__gt=0))
        else:
            qs = qs.filter(date_q)
        qs = qs.distinct()
    elif pay_status == 'unpaid':
        qs = qs.filter(payments__isnull=True)
    elif pay_include_unpaid:
        qs = qs.filter(outstanding_amount__gt=0)
    elif pay_status == 'paid':
        qs = qs.filter(payments__isnull=False).distinct()
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
        _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared'), request)

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
    qs = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
    qs = _apply_record_filters(qs, request)
    qs = _apply_record_state_filters(qs, request, today)
    # 回款日期/含未结清筛选会让 qs 带 payments JOIN，导致后续按维度分组时 Count/Sum
    # 因行扇出而翻倍。先取去重记录 id 落到无 JOIN 的基表，再分组聚合。
    record_ids = list(qs.order_by().values_list('id', flat=True).distinct())
    qs = ARRecord.objects.filter(id__in=record_ids)

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
        perms = get_request_perms(request)
        if perms and perms.get('ar_shared_only') and not pay.ar_record.project.is_shared:
            return err('无权访问', 403)
    denied = _ar_field_denied(request, 'r_payments')
    if denied:
        return denied

    # 「预收抵扣」回款由预收核销自动生成，须在预收预付页改/删对应核销，
    # 不能在此直接编辑或删除（否则两侧台账会失衡）。
    if pay.source == '预收抵扣' and request.method in ('PUT', 'DELETE'):
        return err('该回款由预收核销生成，请在「预收预付」页修改或删除对应核销', 400)

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
                    'short_name': rec.project.short_name or rec.project.contract_name,
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
                    'short_name': rec.project.short_name or rec.project.contract_name,
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

    year = int(request.GET.get('year', datetime.date.today().year))
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

    year = int(request.GET.get('year', datetime.date.today().year))
    qs = _ar_dept_filter(ARRecord.objects.filter(operation_year=year), request,
                         shared_field='project__is_shared')
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
# 预收预付 (Advance receipts / prepayments) — 单表 + direction 判别，挂项目台账
# ══════════════════════════════════════════════════════════════════════════════

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
        if 'direction' in data and data['direction'] in ADVANCE_DIRECTIONS:
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
            rec.advance_amount = _dec(data['advance_amount'])
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

    返回指定方向(默认预收)下、按项目/部门/往来单位过滤后仍有未核销余额
    (balance_amount > 0) 的明细及合计，便于在录入回款（预收）或排款（预付）
    时一眼看到「该客户/项目还有多少预收/预付可冲抵」。只读，不改动任何账务。
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
    project_id = request.GET.get('project_id', '').strip()
    if project_id:
        qs = qs.filter(project_id=int(project_id))
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
        'project_no': r.project.project_no if r.project_id else None,
        'short_name': r.project.short_name if r.project_id else None,
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
    """列出可被预收冲抵的应收明细（同项目、未收余额 > 0），供预收核销弹窗选择。"""
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    project_id = request.GET.get('project_id', '').strip()
    if not project_id:
        return err('缺少 project_id')
    qs = ARRecord.objects.select_related('project').filter(
        project_id=int(project_id), outstanding_amount__gt=0)
    if request.pk_role != 'super_admin':
        qs = qs.filter(delivery_dept__in=request.pk_depts)
    qs = qs.order_by('operation_year', 'operation_month')
    items = [{
        'id': r.id,
        'operation_year': r.operation_year,
        'operation_month': r.operation_month,
        'estimated_amount': str(r.estimated_amount),
        'outstanding_amount': str(r.outstanding_amount),
        'label': (f'{r.operation_year}-{r.operation_month:02d} · 未收 '
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
    created = skipped = updated = 0
    errors = []

    for ri in range(2, ws.max_row + 1):
        direction = _cv(ri, '方向(预收/预付)*')
        short_name = _cv(ri, '项目简称')
        counterparty = _cv(ri, '往来单位*')
        if EXAMPLE_ROW_MARKER in short_name or direction.startswith('★'):
            skipped += 1
            continue
        if direction not in ADVANCE_DIRECTIONS:
            if not direction and not counterparty and not short_name:
                skipped += 1
                continue
            errors.append(f'第{ri}行: 方向无效（应为 预收/预付）')
            skipped += 1
            continue
        proj = None
        dept = _cv(ri, '交付部门')
        if short_name:
            proj = _match_project_by_short_name(short_name, allowed_depts=search_depts)
            if not proj:
                errors.append(f'第{ri}行: 项目简称"{short_name}"未匹配到项目')
                skipped += 1
                continue
            dept = proj.delivery_dept
        if not dept:
            errors.append(f'第{ri}行: 未填项目简称时必须填写交付部门')
            skipped += 1
            continue
        if request.pk_role != 'super_admin' and dept not in request.pk_depts:
            errors.append(f'第{ri}行: 无权操作部门"{dept}"')
            skipped += 1
            continue
        year = int(_cv(ri, '发生年*') or 0)
        month = int(_cv(ri, '发生月*') or 0)
        if not (year and 1 <= month <= 12):
            errors.append(f'第{ri}行: 发生年月无效')
            skipped += 1
            continue
        try:
            rec = AdvanceRecord(
                project=proj, delivery_dept=dept, direction=direction,
                counterparty=counterparty, occur_year=year, occur_month=month,
                occur_date=_normalize_date(_cv_raw(ri, '款项日期')) or None,
                advance_amount=_dec(_cv(ri, '预收/预付金额') or 0),
                expected_writeoff_date=_normalize_date(_cv_raw(ri, '预计核销日期')) or None,
                notes=_cv(ri, '备注'),
                created_by=user,
            )
            rec.save()
            wo_amount = _cv(ri, '核销金额')
            wo_date = _normalize_date(_cv_raw(ri, '核销日期'))
            if wo_amount and wo_date:
                amt = _dec(wo_amount)
                if amt > 0 and not rec.writeoffs.filter(writeoff_date=wo_date, amount=amt).exists():
                    max_no = rec.writeoffs.aggregate(m=Max('writeoff_no')).get('m') or 0
                    AdvanceWriteoff.objects.create(
                        advance_record=rec, writeoff_no=max_no + 1,
                        amount=amt, writeoff_date=wo_date, notes='导入核销')
                    rec.recompute_derived()
            created += 1
        except Exception as e:
            errors.append(f'第{ri}行: {e}')
            skipped += 1

    return ok({'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors})


@csrf_exempt
@pk_required()
def advance_export(request):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    today = datetime.date.today()
    qs = _apply_advance_filters(
        _advance_dept_filter(AdvanceRecord.objects.select_related('project'), request), request)
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
        return ok([w.to_dict() for w in rec.writeoffs.order_by('writeoff_no')])

    if request.method == 'POST':
        denied = _write_denied(request)
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
        try:
            with transaction.atomic():
                last = rec.writeoffs.select_for_update().order_by('-writeoff_no').first()
                next_no = (last.writeoff_no + 1) if last else 1
                wo = AdvanceWriteoff.objects.create(
                    advance_record=rec, writeoff_no=next_no, amount=amount,
                    writeoff_date=wo_date, notes=(data.get('notes') or '').strip())
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

    if request.method == 'PUT':
        denied = _write_denied(request)
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
        denied = _delete_denied(request)
        if denied:
            return denied
        wo.delete()
        return ok({'deleted': wid})

    return err('Method not allowed', 405)


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

    # AR collections by month across all requested depts.
    # 排除「预收抵扣」：其现金已在预收发生时计入流入，重复计会虚增现金。
    ar_coll = (ARPayment.objects
               .filter(payment_date__gte=start_date, payment_date__lte=end_date,
                       ar_record__delivery_dept__in=depts)
               .exclude(source='预收抵扣')
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
    created = skipped = corrected = 0
    errors = []
    warnings = []
    for ri in range(2, ws.max_row + 1):
        short_name = _cv(ri, '项目简称/摘要*')
        if not short_name or EXAMPLE_ROW_MARKER in short_name or short_name.startswith('★'):
            skipped += 1
            continue
        date_str = _normalize_date(_raw_first(ri, date_col_names))
        if not date_str:
            raw_date = _cv_first(ri, date_col_names)
            hint = f'（读到"{raw_date}"）' if raw_date else '（该格为空）'
            errors.append(f'第{ri}行: 预计{lbl}日期无效{hint}，请填 2026-06-15 这样的格式')
            skipped += 1
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
                skipped += 1
                continue
        else:
            # 简称无精确匹配，回退到模糊匹配（容许用户填部分简称）
            proj = _match_project_by_short_name(short_name, filled_dept, search_depts)

        if proj:
            # 以台账为准：用项目的编号/部门/二级部门覆盖填写值
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
            Model.objects.create(
                project_no=project_no,
                short_name=short_name,
                expected_date=date_str,
                sub_dept=sub_dept,
                delivery_dept=dept,
                amount=amount,
                notes=_cv(ri, '备注'),
                created_by=user,
            )
            created += 1
        except Exception as e:
            errors.append(f'第{ri}行: {e}')
            skipped += 1
    return ok({'created': created, 'skipped': skipped, 'corrected': corrected,
               'errors': errors, 'warnings': warnings})


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
