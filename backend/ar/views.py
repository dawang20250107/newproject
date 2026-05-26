import io
import json
import datetime
import calendar
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Sum, Count, Q, F, Value, Case, When, IntegerField, CharField
from django.db.models.functions import TruncMonth
from django.utils import timezone

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from paikuan.views import (pk_required, ok, err, dept_filter, DEPARTMENTS, VALID_DEPARTMENTS,
                           get_request_perms, apply_ar_view_mask)
from ar.models import ARProject, ARRecord, ARPayment, CollectionBudget, PaymentBudget
from paikuan.models import Payment

# ── AR page keys (must match PAGE_KEYS in paikuan/views.py) ───────────────────
AR_PAGE_KEYS = ['ar_projects', 'ar_records', 'ar_analytics', 'ar_cashflow', 'ar_budget']

EXAMPLE_ROW_MARKER = '示例-导入前请删除此行'


def _normalize_date(s):
    s = (str(s) or '').strip()
    if not s or s == 'None':
        return None
    s = s.replace('/', '-').replace('.', '-').replace('年', '-').replace('月', '-').replace('日', '')
    parts = [p for p in s.split('-') if p]
    try:
        if len(parts) >= 3:
            return f'{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}'
    except ValueError:
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
    """Filter queryset by the requesting user's allowed departments."""
    if request.pk_role == 'super_admin':
        return qs
    depts = request.pk_depts
    if not depts:
        return qs.none()
    return qs.filter(**{f'{dept_field}__in': depts})


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
        if _page_denied(request, 'ar_projects'):
            return err('无权创建', 403)
        data = _parse_body(request)
        dept = data.get('delivery_dept', '')
        if dept not in VALID_DEPARTMENTS:
            return err(f'无效交付部门: {dept}')
        # Dept access check
        if request.pk_role != 'super_admin':
            allowed = request.pk_depts
            if dept not in allowed:
                return err('无权操作此部门', 403)
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
                settlement_wait_days=int(data.get('settlement_wait_days', 0) or 0),
                invoice_mode=data.get('invoice_mode', '全额'),
                invoice_type=data.get('invoice_type', ''),
                tax_rate=_dec(data.get('tax_rate', '0')),
                notes=data.get('notes', '').strip(),
                created_by=user,
            )
            p.save()
        except Exception as e:
            return err(str(e))
        return ok(p.to_dict())

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
        data = _parse_body(request)
        for field in ('contract_name', 'short_name', 'sub_dept', 'business_mode',
                      'customer_level', 'sales_contact', 'project_manager',
                      'has_contract', 'invoice_mode', 'invoice_type', 'notes'):
            if field in data:
                setattr(proj, field, data[field])
        if 'contract_date' in data:
            proj.contract_date = _normalize_date(data['contract_date']) or None
        for field in ('reconciliation_days', 'invoice_wait_days', 'settlement_wait_days'):
            if field in data:
                setattr(proj, field, int(data[field] or 0))
        if 'tax_rate' in data:
            proj.tax_rate = _dec(data['tax_rate'])
        if 'delivery_dept' in data:
            dept = data['delivery_dept']
            if dept not in VALID_DEPARTMENTS:
                return err(f'无效交付部门: {dept}')
            proj.delivery_dept = dept
        proj.save()
        return ok(proj.to_dict())

    if request.method == 'DELETE':
        if request.pk_role not in ('super_admin', 'manager'):
            from paikuan.views import get_job_perms
            jt = getattr(request, 'pk_job', '') or ''
            perms = get_job_perms(jt)
            if not perms.get('can_delete'):
                return err('无权删除', 403)
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
    headers = ['合同名称*', '项目简称', '交付部门*', '二级部门', '业务模式',
               '客户等级', '销售对接人*', '项目负责人*', '有无合同',
               '签订日期(YYYY-MM-DD)', '合同对账期(天)', '开票等待期(天)', '结算等待期(天)',
               '开票模式(全额/差额)', '专票/普票', '税率(如0.06)', '备注']
    _header_row(ws, headers)
    example = [EXAMPLE_ROW_MARKER, '物流外包A', '劳务事业部', '华南区', '劳务外包',
               'A级', '张三', '李四', '有', '2026-01-01', 30, 0, 60,
               '全额', '专票', 0.06, '示例备注']
    ws.append(example)
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18
    return _export_response(wb, '项目信息导入模板.xlsx')


@csrf_exempt
@pk_required()
def project_import(request):
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
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
    created = skipped = 0
    errors = []

    for ri in range(2, ws.max_row + 1):
        contract_name = _cv(ri, '合同名称*')
        if not contract_name or EXAMPLE_ROW_MARKER in contract_name:
            skipped += 1
            continue
        dept = _cv(ri, '交付部门*')
        if dept not in VALID_DEPARTMENTS:
            errors.append(f'第{ri}行: 无效交付部门"{dept}"')
            skipped += 1
            continue
        if request.pk_role != 'super_admin':
            allowed = request.pk_depts
            if dept not in allowed:
                errors.append(f'第{ri}行: 无权操作部门"{dept}"')
                skipped += 1
                continue
        try:
            tax_raw = _cv(ri, '税率(如0.06)')
            p = ARProject(
                contract_name=contract_name,
                short_name=_cv(ri, '项目简称'),
                delivery_dept=dept,
                sub_dept=_cv(ri, '二级部门'),
                business_mode=_cv(ri, '业务模式'),
                customer_level=_cv(ri, '客户等级'),
                sales_contact=_cv(ri, '销售对接人*'),
                project_manager=_cv(ri, '项目负责人*'),
                has_contract=_cv(ri, '有无合同') or '无',
                contract_date=_normalize_date(_cv(ri, '签订日期(YYYY-MM-DD)')) or None,
                reconciliation_days=int(_cv(ri, '合同对账期(天)') or 0),
                invoice_wait_days=int(_cv(ri, '开票等待期(天)') or 0),
                settlement_wait_days=int(_cv(ri, '结算等待期(天)') or 0),
                invoice_mode=_cv(ri, '开票模式(全额/差额)') or '全额',
                invoice_type=_cv(ri, '专票/普票'),
                tax_rate=_dec(tax_raw),
                notes=_cv(ri, '备注'),
                created_by=user,
            )
            p.save()
            created += 1
        except Exception as e:
            errors.append(f'第{ri}行: {e}')
            skipped += 1

    return ok({'created': created, 'skipped': skipped, 'errors': errors})


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
    headers = ['项目编号', '合同名称', '项目简称', '交付部门', '二级部门', '业务模式',
               '客户等级', '销售对接人', '项目负责人', '共享业务', '有无合同', '签订日期',
               '合同对账期(天)', '开票等待期(天)', '结算等待期(天)', '总账期(天)',
               '开票模式', '专票/普票', '税率', '备注']
    _header_row(ws, headers)
    for p in qs:
        ws.append([
            p.project_no, p.contract_name, p.short_name, p.delivery_dept,
            p.sub_dept, p.business_mode, p.customer_level, p.sales_contact,
            p.project_manager, '是' if p.is_shared else '否', p.has_contract,
            str(p.contract_date) if p.contract_date else '',
            p.reconciliation_days, p.invoice_wait_days, p.settlement_wait_days,
            p.total_days, p.invoice_mode, p.invoice_type, str(p.tax_rate), p.notes,
        ])
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
        qs = _ar_dept_filter(ARRecord.objects.select_related('project', 'created_by'), request)

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

        # Status filter
        status = request.GET.get('status', '').strip()
        eomonth_today = datetime.date(today.year, today.month,
                                      calendar.monthrange(today.year, today.month)[1])
        if status == 'overdue':
            qs = qs.filter(outstanding_amount__gt=0, due_date__lt=today)
        elif status == 'current':
            qs = qs.filter(outstanding_amount__gt=0, due_date__gte=today,
                           due_date__lte=eomonth_today)
        elif status == 'not_due':
            qs = qs.filter(outstanding_amount__gt=0, due_date__gt=eomonth_today)
        elif status == 'settled':
            qs = qs.filter(outstanding_amount__lte=0)

        # Invoice status
        inv_status = request.GET.get('invoice_status', '').strip()
        if inv_status == '未开票':
            qs = qs.filter(actual_invoice_amount__isnull=True)
        elif inv_status == '已结清':
            qs = qs.filter(outstanding_amount__lte=0, actual_invoice_amount__isnull=False)
        elif inv_status == '已开票':
            qs = qs.filter(actual_invoice_amount__isnull=False, outstanding_amount__gt=0)

        # Reconciliation status
        recon_status = request.GET.get('reconciliation_status', '').strip()
        if recon_status == '已对账':
            qs = qs.filter(reconciliation_time__isnull=False)
        elif recon_status == '未对账':
            qs = qs.filter(reconciliation_time__isnull=True)

        # Date range on due_date
        due_start = request.GET.get('due_start', '').strip()
        due_end = request.GET.get('due_end', '').strip()
        if due_start:
            qs = qs.filter(due_date__gte=due_start)
        if due_end:
            qs = qs.filter(due_date__lte=due_end)

        include_payments = request.GET.get('include_payments', '') in ('1', 'true')
        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
        total = qs.count()
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

        return ok({'items': rows, 'total': total, 'page': page, 'size': size})

    if request.method == 'POST':
        data = _parse_body(request)
        project_id = data.get('project_id')
        if not project_id:
            return err('缺少 project_id')
        try:
            proj = ARProject.objects.get(pk=int(project_id))
        except ARProject.DoesNotExist:
            return err('项目不存在', 404)
        if request.pk_role != 'super_admin':
            allowed = request.pk_depts
            if proj.delivery_dept not in allowed:
                return err('无权操作此部门', 403)
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
                reconciliation_time=data.get('reconciliation_time') or None,
                notes=data.get('notes', '').strip(),
                created_by=user,
            )
            rec.save()
        except Exception as e:
            return err(str(e))
        return ok(rec.to_dict(today=datetime.date.today(), include_payments=True))

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
        data = _parse_body(request)
        for field in ('estimated_amount',):
            if field in data:
                setattr(rec, field, _dec(data[field]))
        if 'actual_invoice_amount' in data:
            rec.actual_invoice_amount = _dec(data['actual_invoice_amount']) if data['actual_invoice_amount'] not in (None, '') else None
        if 'tax_amount' in data:
            rec.tax_amount = _dec(data['tax_amount']) if data['tax_amount'] not in (None, '') else None
        if 'invoice_date' in data:
            rec.invoice_date = _normalize_date(data['invoice_date']) or None
        if 'reconciliation_time' in data:
            rec.reconciliation_time = data['reconciliation_time'] or None
        if 'notes' in data:
            rec.notes = data['notes'].strip()
        rec.save()
        return ok(rec.to_dict(today=today, include_payments=True))

    if request.method == 'DELETE':
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
    headers = ['项目编号*', '运作年*', '运作月*', '预估上账金额', '实际开票金额',
               '税额(差额模式手填)', '开票日期(YYYY-MM-DD)', '备注']
    _header_row(ws, headers, color='1B6E35')
    ws.append([EXAMPLE_ROW_MARKER, 2026, 1, 100000, 100000, '', '2026-01-15', '示例'])
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20
    return _export_response(wb, '应收账款明细导入模板.xlsx')


@csrf_exempt
@pk_required()
def ar_record_import(request):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
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
    created = skipped = updated = 0
    errors = []

    for ri in range(2, ws.max_row + 1):
        project_no = _cv(ri, '项目编号*')
        if not project_no or EXAMPLE_ROW_MARKER in project_no:
            skipped += 1
            continue
        try:
            proj = ARProject.objects.get(project_no=project_no)
        except ARProject.DoesNotExist:
            errors.append(f'第{ri}行: 项目编号"{project_no}"不存在')
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
            rec, created_new = ARRecord.objects.get_or_create(
                project=proj, operation_year=year, operation_month=month,
                defaults={'created_by': user})
            est = _cv(ri, '预估上账金额')
            if est:
                rec.estimated_amount = _dec(est)
            actual = _cv(ri, '实际开票金额')
            rec.actual_invoice_amount = _dec(actual) if actual else None
            tax_raw = _cv(ri, '税额(差额模式手填)')
            rec.tax_amount = _dec(tax_raw) if tax_raw else None
            inv_date = _normalize_date(_cv(ri, '开票日期(YYYY-MM-DD)'))
            rec.invoice_date = inv_date or None
            notes = _cv(ri, '备注')
            rec.notes = notes
            rec.save()
            if created_new:
                created += 1
            else:
                updated += 1
        except Exception as e:
            errors.append(f'第{ri}行: {e}')
            skipped += 1

    return ok({'created': created, 'updated': updated, 'skipped': skipped, 'errors': errors})


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
    headers = ['项目编号', '项目简称', '合同名称', '交付部门', '项目负责人',
               '销售对接人', '总账期(天)', '运作年', '运作月',
               '预估上账金额', '实际开票金额', '税额', '开票日期', '开票模式',
               '账实差额调整', '未回款金额', '应收日期',
               '对账状态', '对账时间', '开票状态', '是否逾期', '逾期天数', '备注']
    _header_row(ws, headers, color='1B6E35')
    for rec in qs:
        st = rec.status_dict(today)
        ws.append([
            rec.project.project_no, rec.project.short_name, rec.project.contract_name,
            rec.delivery_dept, rec.project.project_manager, rec.project.sales_contact,
            rec.project.total_days, rec.operation_year, rec.operation_month,
            float(rec.estimated_amount),
            float(rec.actual_invoice_amount) if rec.actual_invoice_amount is not None else '',
            float(rec.tax_amount) if rec.tax_amount is not None else '',
            str(rec.invoice_date) if rec.invoice_date else '',
            rec.project.invoice_mode,
            float(rec.account_diff_adjustment),
            float(rec.outstanding_amount),
            str(rec.due_date) if rec.due_date else '',
            rec.reconciliation_status,
            rec.reconciliation_time.strftime('%Y-%m-%d') if rec.reconciliation_time else '',
            rec.invoice_status,
            '是' if st['is_overdue'] else '',
            st['overdue_days'] if st['is_overdue'] else '',
            rec.notes,
        ])
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
    recon_done = qs.filter(reconciliation_time__isnull=False).count()
    recon_pending = total - recon_done

    # Invoice: 已开票 vs 未开票
    inv_done = qs.filter(actual_invoice_amount__isnull=False).count()
    inv_pending = total - inv_done

    # Collection: 已结清 vs 未收
    settled = qs.filter(outstanding_amount__lte=0).count()
    outstanding_qs = qs.filter(outstanding_amount__gt=0)
    outstanding_count = outstanding_qs.count()
    outstanding_amount = outstanding_qs.aggregate(s=Sum('outstanding_amount'))['s'] or 0

    # Overdue (within current filter)
    overdue_qs = qs.filter(outstanding_amount__gt=0, due_date__lt=today)
    overdue_count = overdue_qs.count()
    overdue_amount = overdue_qs.aggregate(s=Sum('outstanding_amount'))['s'] or 0

    def _rate(done, tot):
        return round(done / tot * 100, 1) if tot else 100.0

    return ok({
        'total': total,
        'reconciliation': {
            'done': recon_done, 'pending': recon_pending,
            'rate': _rate(recon_done, total),
            'pending_amount': str(qs.filter(reconciliation_time__isnull=True)
                                  .aggregate(s=Sum('outstanding_amount'))['s'] or 0),
        },
        'invoice': {
            'done': inv_done, 'pending': inv_pending,
            'rate': _rate(inv_done, total),
        },
        'collection': {
            'settled': settled,
            'outstanding_count': outstanding_count,
            'outstanding_amount': str(outstanding_amount),
            'rate': _rate(settled, total),
        },
        'overdue': {'count': overdue_count, 'amount': str(overdue_amount)},
    })


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

    if request.method == 'GET':
        pays = list(rec.payments.order_by('payment_no'))
        return ok([p.to_dict() for p in pays])

    if request.method == 'POST':
        data = _parse_body(request)
        amount = _dec(data.get('amount', 0))
        if amount <= 0:
            return err('回款金额必须大于0')
        pay_date = _normalize_date(data.get('payment_date'))
        if not pay_date:
            return err('回款日期无效')
        with transaction.atomic():
            last = rec.payments.order_by('-payment_no').first()
            next_no = (last.payment_no + 1) if last else 1
            pay = ARPayment.objects.create(
                ar_record=rec,
                payment_no=next_no,
                amount=amount,
                payment_date=pay_date,
                notes=data.get('notes', '').strip(),
            )
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

    if request.method == 'PUT':
        data = _parse_body(request)
        if 'amount' in data:
            pay.amount = _dec(data['amount'])
        if 'payment_date' in data:
            pay.payment_date = _normalize_date(data['payment_date']) or pay.payment_date
        if 'notes' in data:
            pay.notes = data['notes'].strip()
        pay.save()
        return ok(pay.to_dict())

    if request.method == 'DELETE':
        pay.delete()
        return ok({'deleted': ppk})

    return err('Method not allowed', 405)


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

    by_month = {}
    for rec in qs.annotate(total_paid=Sum('payments__amount')):
        m = rec.operation_month
        base = float(rec.actual_invoice_amount or rec.estimated_amount or 0)
        paid = float(rec.total_paid or 0)
        if m not in by_month:
            by_month[m] = {'receivable': 0.0, 'collected': 0.0}
        by_month[m]['receivable'] += base
        by_month[m]['collected'] += paid

    months = []
    for m in range(1, 13):
        entry = by_month.get(m, {'receivable': 0.0, 'collected': 0.0})
        rate = (entry['collected'] / entry['receivable'] * 100) if entry['receivable'] else 0
        months.append({
            'month': m,
            'receivable': round(entry['receivable'], 2),
            'collected': round(entry['collected'], 2),
            'rate': round(rate, 2),
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


# ══════════════════════════════════════════════════════════════════════════════
# Cashflow comparison (AR collected vs AP paid)
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@pk_required()
def cashflow(request):
    denied = _page_denied(request, 'ar_cashflow')
    if denied:
        return denied

    # Date range
    today = datetime.date.today()
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
        data = _parse_body(request)
        dept = data.get('delivery_dept', '').strip()
        if dept and dept not in VALID_DEPARTMENTS:
            return err(f'无效交付部门: {dept}')
        date_str = _normalize_date(data.get('expected_date'))
        if not date_str:
            return err('预计日期无效')
        amount = _dec(data.get('amount', 0))
        if amount <= 0:
            return err('金额必须大于0')
        from paikuan.models import PaikuanUser
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        obj = Model.objects.create(
            project_no=data.get('project_no', '').strip(),
            short_name=data.get('short_name', '').strip(),
            expected_date=date_str,
            sub_dept=data.get('sub_dept', '').strip(),
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

    if request.method == 'GET':
        return ok(obj.to_dict())

    if request.method == 'PUT':
        data = _parse_body(request)
        for field in ('project_no', 'short_name', 'sub_dept', 'notes'):
            if field in data:
                setattr(obj, field, data[field])
        if 'delivery_dept' in data:
            dept = data['delivery_dept']
            if dept and dept not in VALID_DEPARTMENTS:
                return err(f'无效交付部门: {dept}')
            obj.delivery_dept = dept
        if 'expected_date' in data:
            obj.expected_date = _normalize_date(data['expected_date']) or obj.expected_date
        if 'amount' in data:
            obj.amount = _dec(data['amount'])
        obj.save()
        return ok(obj.to_dict())

    if request.method == 'DELETE':
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
        if dept and dept not in VALID_DEPARTMENTS:
            errors.append(f'第{ri}行: 无效交付部门"{dept}"')
            skipped += 1
            continue
        if dept and request.pk_role != 'super_admin' and dept not in request.pk_depts:
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
                project_no=_cv(ri, '项目编号(可选)'),
                short_name=short_name,
                expected_date=date_str,
                sub_dept=_cv(ri, '二级部门'),
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
        depts = DEPARTMENTS
    else:
        depts = request.pk_depts
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
    })
