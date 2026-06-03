import io
import re
import json
import logging
import datetime
import functools
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Sum, Q
from django.conf import settings
from django.utils import timezone
import jwt

from caiwu.models import (
    L1Category, L2Category, L3Category,
    ImportBatch, FinancialEntry, FinancialTarget,
    BUSINESS_UNITS, VALID_BUSINESS_UNITS, JOB_TITLES,
)
from paikuan.models import PaikuanUser, JobPermission as PaikuanJobPermission

logger = logging.getLogger('caiwu')

BUILD_VERSION = '2026-05-24.2'

EXCEL_HEADERS = ['一级科目', '二级项目部', '三级科目明细', '借方(元)', '贷方(元)']
PL_HEADERS = ['科目名称', '本期金额']  # 利润表模板格式
IMPORT_SIZE_LIMIT = 5 * 1024 * 1024  # 5 MB

# Hardcoded KXT P&L calculation formulas.
# Keys are L1 category names; each lambda receives a name->float dict
# (built in sort_order so earlier results are available to later ones).
_CALC_FORMULAS = {
    '运营毛利': lambda m: (
        m.get('主营业务收入', 0) - m.get('主营业务成本', 0) - m.get('税金成本', 0)
    ),
    '经营毛利': lambda m: (
        m.get('运营毛利', 0)
        - m.get('销售费用', 0) - m.get('管理费用', 0) - m.get('财务费用', 0)
        + m.get('营业外收入', 0) - m.get('营业外支出', 0)
    ),
    '经营净利': lambda m: m.get('经营毛利', 0) - m.get('集团管理费用', 0),
}


def _compute_l1_name_map(l1_cats, raw_by_id):
    """
    Build name->float dict for all L1 categories (sorted by sort_order).
    Raw rows are filled from raw_by_id; calculated rows use _CALC_FORMULAS.
    Returns (name_map, id_map) where id_map is l1_id->float.
    """
    name_map = {}
    id_map = {}
    for l1 in l1_cats:
        if l1.is_calculated:
            formula = _CALC_FORMULAS.get(l1.name)
            if formula:
                val = formula(name_map)
                name_map[l1.name] = val
                id_map[l1.id] = val
        else:
            val = raw_by_id.get(l1.id)
            if val is not None:
                name_map[l1.name] = float(val)
                id_map[l1.id] = float(val)
    return name_map, id_map


# ── granular job-title permission system (mirrors paikuan) ────────────────────

# View-controllable report/chart elements. Each job title can be granted or
# denied visibility of each one (super_admin always sees everything).
PERM_FIELD_DEFS = [
    {'key': 'report_l1',       'label': '一级科目报表'},
    {'key': 'report_l2',       'label': '二级项目部明细'},
    {'key': 'report_l3',       'label': '三级科目明细'},
    {'key': 'amount',          'label': '金额数据'},
    {'key': 'chart_trend',     'label': '走势折线图'},
    {'key': 'chart_waterfall', 'label': '因素瀑布图'},
    {'key': 'export',          'label': '导出 Excel'},
]
FIELD_KEYS = [f['key'] for f in PERM_FIELD_DEFS]
PAGE_DEFS = [
    {'key': 'report',  'label': '财务报表'},
    {'key': 'data',    'label': '数据加工'},
    {'key': 'charts',  'label': '报表分析'},
    {'key': 'metrics', 'label': '指标管理'},
    {'key': 'cockpit', 'label': '财务驾驶舱'},
]
PAGE_KEYS = [p['key'] for p in PAGE_DEFS]


def _all_fields(value):
    return {k: value for k in FIELD_KEYS}


def _caiwu_perms_from_pk(pk):
    """Project paikuan's unified perms dict onto the caiwu-shaped subset."""
    from paikuan.views import CAIWU_FIELD_KEYS
    pk_pages = pk.get('pages', {})
    return {
        'pages': {
            'report':  bool(pk_pages.get('caiwu_report',  False)),
            'data':    bool(pk_pages.get('caiwu_data',    False)),
            'charts':  bool(pk_pages.get('caiwu_charts',  False)),
            'metrics': bool(pk_pages.get('caiwu_metrics', False)),
            'cockpit': bool(pk_pages.get('caiwu_cockpit', False)),
        },
        'view':        dict(pk.get('caiwu_view', {k: True for k in CAIWU_FIELD_KEYS})),
        'can_upload':  bool(pk.get('caiwu_upload',  False)),
        'can_publish': bool(pk.get('caiwu_publish', False)),
        'can_delete':  bool(pk.get('caiwu_delete',  False)),
    }


def default_job_config(job):
    """caiwu perm subset of paikuan's default job config (no stored overrides)."""
    from paikuan.views import default_job_config as pk_default
    return _caiwu_perms_from_pk(pk_default(job))


def _invalidate_perm_cache(job=None):
    """Caiwu keeps no perm cache of its own — it derives perms on demand from
    paikuan's cached get_job_perms. Kept as a no-op so cross-module callers and
    the standalone permission_detail endpoint don't break."""
    return None


def get_job_perms(job):
    """Effective caiwu config for a job title.

    Derived on demand from paikuan's get_job_perms (itself cached and
    invalidated whenever a JobPermission is edited). A single cache in paikuan
    avoids a second, separately-invalidated cache drifting out of sync.
    """
    from paikuan.views import get_job_perms as pk_get_job_perms
    return _caiwu_perms_from_pk(pk_get_job_perms(job))


def full_perms():
    return {'pages': {k: True for k in PAGE_KEYS}, 'view': _all_fields(True),
            'can_upload': True, 'can_publish': True, 'can_delete': True}


def effective_perms(user):
    """Perms object sent to the client. Works with PaikuanUser (super_admin gets full access)."""
    cfg = full_perms() if user.role == 'super_admin' else get_job_perms(user.job_title)
    return {**cfg, 'is_admin': user.role == 'super_admin',
            'fields': PERM_FIELD_DEFS, 'pages_meta': PAGE_DEFS}


def get_request_perms(request):
    """Effective perms for the authed request. None means full access (super_admin)."""
    if request.pk_role == 'super_admin':
        return None
    jt = getattr(request, 'pk_job', '') or ''
    return get_job_perms(jt)


def _can_view(request, field_key):
    p = get_request_perms(request)
    return True if p is None else bool(p['view'].get(field_key, True))


def _page_denied(request, page):
    """Return an err() response if the request's job lacks access to a page, else None."""
    p = get_request_perms(request)
    if p is not None and not p['pages'].get(page, True):
        return err('无访问权限', 403, 403)
    return None


# ── helpers ─────────────────────────────────────────────────────────────────

def ok(data=None, **extra):
    body = {'code': 0}
    if data is not None:
        body['data'] = data
    body.update(extra)
    return JsonResponse(body)


def err(msg, status=400, code=400):
    return JsonResponse({'code': code, 'error': msg}, status=status)


def _parse_json(request):
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def _make_token(user):
    payload = {
        'uid': user.id,
        'role': user.role,
        'job': user.job_title,
        'departments': user.departments,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        'iat': datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm='HS256')


def _build_excel_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    ascii_fallback = filename.encode('ascii', 'ignore').decode() or 'export.xlsx'
    encoded = quote(filename.encode('utf-8'), safe='')
    response['Content-Disposition'] = (
        f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
    )
    return response


# ── auth decorator ───────────────────────────────────────────────────────────

def cw_required(roles=None):
    """Auth decorator backed by PaikuanUser (Stage 2+3 unified accounts)."""
    def decorator(func):
        @functools.wraps(func)
        @csrf_exempt
        def wrapper(request, *args, **kwargs):
            token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
            if not token:
                return err('未认证', 401, 401)
            try:
                payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
                uid = payload['uid']
            except jwt.ExpiredSignatureError:
                return err('Token已过期', 401, 401)
            except jwt.InvalidTokenError:
                return err('Token无效', 401, 401)
            user = PaikuanUser.objects.filter(id=uid).first()
            if not user:
                return err('用户不存在', 401, 401)
            if not user.is_active:
                return err('账号已停用', 401, 401)
            if not user.is_approved:
                return err('账号待审批，请联系管理员', 403, 403)
            request.pk_user = user
            request.pk_uid = user.id
            request.pk_role = user.role
            request.pk_job = user.job_title
            request.pk_depts = user.departments or []
            if roles and request.pk_role not in roles:
                return err('权限不足', 403, 403)
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def _bu_filter(qs, request):
    """Row visibility: super_admin sees all; everyone else sees assigned 事业部."""
    if request.pk_role == 'super_admin':
        return qs
    return qs.filter(business_unit__in=request.pk_depts)


def _can_access_bu(request, bu):
    if request.pk_role == 'super_admin':
        return True
    return bu in request.pk_depts


def _can_upload(request):
    p = get_request_perms(request)
    return True if p is None else bool(p.get('can_upload'))


def _can_publish(request):
    p = get_request_perms(request)
    return True if p is None else bool(p.get('can_publish'))


def _can_delete(request):
    p = get_request_perms(request)
    return True if p is None else bool(p.get('can_delete'))


# ── auth views ───────────────────────────────────────────────────────────────

@csrf_exempt
def register(request):
    """Disabled — account management moved to paikuan platform."""
    return err('财务分析账号已与排款平台统一，请通过排款平台登录', 410, 410)


@csrf_exempt
def login(request):
    """Disabled — use paikuan platform login (/api/pk/login)."""
    return err('财务分析账号已与排款平台统一，请通过排款平台登录', 410, 410)


@csrf_exempt
def registration_status(request):
    """Disabled — use paikuan platform."""
    return err('财务分析账号已与排款平台统一', 410, 410)


@cw_required()
def me(request):
    if request.method != 'GET':
        return err('方法不允许', 405)
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    if not user:
        return err('用户不存在', 404)
    token = _make_token(user)
    return ok({'token': token, 'user': user.to_dict(), 'permissions': effective_perms(user)})


# ── user management ──────────────────────────────────────────────────────────

@cw_required(roles=['super_admin'])
def users(request):
    """User management moved to paikuan platform."""
    return err('账号管理已统一至排款平台，请通过排款平台管理用户', 410, 410)


@cw_required(roles=['super_admin'])
def user_detail(request, uid):
    return err('账号管理已统一至排款平台', 410, 410)


@cw_required(roles=['super_admin'])
def user_approve(request, uid):
    return err('账号管理已统一至排款平台', 410, 410)


@cw_required(roles=['super_admin'])
def user_reject(request, uid):
    return err('账号管理已统一至排款平台', 410, 410)


# ── job-title permission config (super_admin) ────────────────────────────────

@cw_required(roles=['super_admin'])
def permissions(request):
    """GET: full caiwu permission matrix (sourced from paikuan JobPermission)."""
    if request.method != 'GET':
        return err('方法不允许', 405)
    jobs = [
        {'job_title': key, 'label': label, 'config': get_job_perms(key)}
        for key, label in JOB_TITLES.items()
    ]
    return ok({'fields': PERM_FIELD_DEFS, 'pages': PAGE_DEFS, 'jobs': jobs})


@cw_required(roles=['super_admin'])
def permission_detail(request, job):
    """PUT: update caiwu-specific keys inside paikuan's JobPermission."""
    if request.method != 'PUT':
        return err('方法不允许', 405)
    if job not in JOB_TITLES:
        return err('职务无效', 404)
    body = _parse_json(request)
    cfg = body.get('config') or {}
    obj, _ = PaikuanJobPermission.objects.get_or_create(job_title=job)
    existing = dict(obj.config or {})
    # Write caiwu-specific fields into paikuan's config namespace
    existing['caiwu_view'] = {k: bool(cfg.get('view', {}).get(k, True)) for k in FIELD_KEYS}
    existing.setdefault('pages', {})
    existing['pages']['caiwu_report'] = bool(cfg.get('pages', {}).get('report', True))
    existing['pages']['caiwu_data']   = bool(cfg.get('pages', {}).get('data',   True))
    existing['pages']['caiwu_charts'] = bool(cfg.get('pages', {}).get('charts', True))
    existing['caiwu_upload']  = bool(cfg.get('can_upload', False))
    existing['caiwu_publish'] = bool(cfg.get('can_publish', False))
    existing['caiwu_delete']  = bool(cfg.get('can_delete', False))
    obj.config = existing
    obj.save()
    # Perms live in paikuan's JobPermission + cache (single source of truth).
    from paikuan.views import _invalidate_perm_cache as _pk_invalidate
    _pk_invalidate(job)
    return ok({'job_title': job, 'config': get_job_perms(job)})


# ── category management ──────────────────────────────────────────────────────

@cw_required(roles=['super_admin'])
def categories_l1(request):
    if request.method == 'GET':
        return ok([c.to_dict() for c in L1Category.objects.all()])
    if request.method == 'POST':
        body = _parse_json(request)
        name = (body.get('name') or '').strip()
        if not name:
            return err('科目名称不能为空')
        if L1Category.objects.filter(name=name).exists():
            return err('该科目已存在')
        sign = int(body.get('sign', 1))
        if sign not in (1, -1):
            sign = 1
        cat = L1Category.objects.create(
            name=name,
            sort_order=body.get('sort_order', 0),
            is_profit_driver=bool(body.get('is_profit_driver', False)),
            is_calculated=bool(body.get('is_calculated', False)),
            sign=sign,
        )
        return ok(cat.to_dict())
    return err('方法不允许', 405)


@cw_required(roles=['super_admin'])
def category_l1_detail(request, cid):
    try:
        cat = L1Category.objects.get(id=cid)
    except L1Category.DoesNotExist:
        return err('科目不存在', 404)
    if request.method == 'PUT':
        body = _parse_json(request)
        name = (body.get('name') or '').strip()
        if not name:
            return err('科目名称不能为空')
        if L1Category.objects.filter(name=name).exclude(id=cid).exists():
            return err('该名称已被其他科目使用')
        sign = int(body.get('sign', cat.sign))
        if sign not in (1, -1):
            sign = cat.sign
        cat.name = name
        cat.sort_order = body.get('sort_order', cat.sort_order)
        cat.is_profit_driver = bool(body.get('is_profit_driver', cat.is_profit_driver))
        cat.is_calculated = bool(body.get('is_calculated', cat.is_calculated))
        cat.sign = sign
        cat.save()
        return ok(cat.to_dict())
    if request.method == 'DELETE':
        if cat.entries.exists():
            return err('该科目已有数据，无法删除')
        cat.delete()
        return ok({'deleted': cid})
    return err('方法不允许', 405)


@cw_required(roles=['super_admin'])
def categories_l2(request):
    bu = request.GET.get('bu', '')
    if request.method == 'GET':
        qs = L2Category.objects.all()
        if bu:
            qs = qs.filter(business_unit=bu)
        return ok([c.to_dict() for c in qs])
    if request.method == 'POST':
        body = _parse_json(request)
        bu = (body.get('business_unit') or bu or '').strip()
        name = (body.get('name') or '').strip()
        if not bu or not name:
            return err('事业部和项目部名称不能为空')
        if bu not in VALID_BUSINESS_UNITS:
            return err('无效的事业部')
        if L2Category.objects.filter(business_unit=bu, name=name).exists():
            return err('该项目部已存在')
        cat = L2Category.objects.create(
            business_unit=bu, name=name,
            sort_order=body.get('sort_order', 0),
        )
        return ok(cat.to_dict())
    return err('方法不允许', 405)


@cw_required(roles=['super_admin'])
def category_l2_detail(request, cid):
    try:
        cat = L2Category.objects.get(id=cid)
    except L2Category.DoesNotExist:
        return err('项目部不存在', 404)
    if request.method == 'PUT':
        body = _parse_json(request)
        name = (body.get('name') or '').strip()
        if not name:
            return err('名称不能为空')
        if L2Category.objects.filter(business_unit=cat.business_unit, name=name).exclude(id=cid).exists():
            return err('该名称已存在')
        cat.name = name
        cat.sort_order = body.get('sort_order', cat.sort_order)
        cat.save()
        return ok(cat.to_dict())
    if request.method == 'DELETE':
        if cat.entries.exists():
            return err('该项目部已有数据，无法删除')
        cat.delete()
        return ok({'deleted': cid})
    return err('方法不允许', 405)


@cw_required(roles=['super_admin'])
def categories_l3(request):
    bu = request.GET.get('bu', '')
    if request.method == 'GET':
        qs = L3Category.objects.select_related('l1_category').all()
        if bu:
            qs = qs.filter(business_unit=bu)
        return ok([c.to_dict() for c in qs])
    if request.method == 'POST':
        body = _parse_json(request)
        bu = (body.get('business_unit') or bu or '').strip()
        name = (body.get('name') or '').strip()
        l1_id = body.get('l1_category_id')
        if not bu or not name:
            return err('事业部和科目明细不能为空')
        if bu not in VALID_BUSINESS_UNITS:
            return err('无效的事业部')
        l1 = None
        if l1_id:
            try:
                l1 = L1Category.objects.get(id=l1_id)
            except L1Category.DoesNotExist:
                return err('一级科目不存在')
        if L3Category.objects.filter(business_unit=bu, l1_category=l1, name=name).exists():
            return err('该科目明细已存在')
        cat = L3Category.objects.create(
            business_unit=bu, l1_category=l1, name=name,
            sort_order=body.get('sort_order', 0),
            kingdee_code=(body.get('kingdee_code') or '').strip(),
        )
        return ok(cat.to_dict())
    return err('方法不允许', 405)


@cw_required(roles=['super_admin'])
def category_l3_detail(request, cid):
    try:
        cat = L3Category.objects.get(id=cid)
    except L3Category.DoesNotExist:
        return err('科目明细不存在', 404)
    if request.method == 'PUT':
        body = _parse_json(request)
        name = (body.get('name') or '').strip()
        if not name:
            return err('名称不能为空')
        l1_id = body.get('l1_category_id', cat.l1_category_id)
        l1 = None
        if l1_id:
            try:
                l1 = L1Category.objects.get(id=l1_id)
            except L1Category.DoesNotExist:
                return err('一级科目不存在')
        if L3Category.objects.filter(
            business_unit=cat.business_unit, l1_category=l1, name=name,
        ).exclude(id=cid).exists():
            return err('该名称已存在')
        cat.name = name
        cat.l1_category = l1
        cat.sort_order = body.get('sort_order', cat.sort_order)
        cat.kingdee_code = (body.get('kingdee_code') or '').strip()
        cat.save()
        return ok(cat.to_dict())
    if request.method == 'DELETE':
        if cat.entries.exists():
            return err('该科目已有数据，无法删除')
        cat.delete()
        return ok({'deleted': cid})
    return err('方法不允许', 405)


# ── batch / import ───────────────────────────────────────────────────────────

@cw_required()
def batches(request):
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'data')
    if denied:
        return denied
    qs = _bu_filter(ImportBatch.objects.all(), request)
    year = request.GET.get('year')
    month = request.GET.get('month')
    status = request.GET.get('status')
    if year:
        qs = qs.filter(year=year)
    if month:
        qs = qs.filter(month=month)
    if status:
        qs = qs.filter(status=status)
    return ok([b.to_dict() for b in qs[:200]])


@cw_required()
def batch_template(request):
    if request.method != 'GET':
        return err('方法不允许', 405)
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return err('服务器缺少 openpyxl 依赖')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '财务数据导入模板'

    header_fill = PatternFill(start_color='C96342', end_color='C96342', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True)

    for col, header in enumerate(EXCEL_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    # Example rows (revenue + cost)
    ws.cell(row=2, column=1, value='主营业务收入')
    ws.cell(row=2, column=2, value='甲项目部（可选）')
    ws.cell(row=2, column=3, value='（可选）')
    ws.cell(row=2, column=4, value=0)         # 借方
    ws.cell(row=2, column=5, value=1000000.00)  # 贷方（收入在贷方）
    ws.cell(row=3, column=1, value='主营业务成本')
    ws.cell(row=3, column=2, value='甲项目部（可选）')
    ws.cell(row=3, column=3, value='（可选）')
    ws.cell(row=3, column=4, value=600000.00)  # 借方（成本在借方）
    ws.cell(row=3, column=5, value=0)

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 24
    ws.column_dimensions['D'].width = 14
    ws.column_dimensions['E'].width = 14

    # Instruction sheet
    ws2 = wb.create_sheet('填写说明')
    instructions = [
        ['列名', '说明', '是否必填'],
        ['一级科目', '必须与系统中已配置的一级科目名称完全一致', '必填'],
        ['二级项目部', '该事业部下的项目部名称，系统会自动创建不存在的项目部', '选填'],
        ['三级科目明细', '成本费用科目明细，系统会自动创建不存在的明细', '选填'],
        ['借方(元)', '会计借方发生额（成本费用在此列）', '二选一'],
        ['贷方(元)', '会计贷方发生额（收入在此列）', '二选一'],
        ['', '', ''],
        ['注意：借贷方向说明', '', ''],
        ['收入类科目（主营业务收入等）', '贷方填金额，借方填0', ''],
        ['成本费用类科目', '借方填金额，贷方填0', ''],
        ['红字冲销（负数）', '直接在对应列填负数', ''],
        ['', '', ''],
        ['注意事项', '', ''],
        ['1. 上传时须指定事业部、年份、月份', '', ''],
        ['2. 同一事业部同月份只能有一个已发布的数据批次', '', ''],
        ['3. 发布后旧数据自动归档，新数据生效', '', ''],
    ]
    for row in instructions:
        ws2.append(row)
    ws2.column_dimensions['A'].width = 18
    ws2.column_dimensions['B'].width = 40
    ws2.column_dimensions['C'].width = 10

    # Profit & Loss template sheet
    ws3 = wb.create_sheet('利润表模板')
    pl_fill = PatternFill(start_color='1565C0', end_color='1565C0', fill_type='solid')
    for col, h in enumerate(PL_HEADERS, 1):
        cell = ws3.cell(row=1, column=col, value=h)
        cell.fill = pl_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')
    l1_cats = list(L1Category.objects.order_by('sort_order', 'id').all())
    for ri, cat in enumerate(l1_cats, 2):
        ws3.cell(row=ri, column=1, value=cat.name)
        ws3.cell(row=ri, column=2, value=0)
    ws3.column_dimensions['A'].width = 22
    ws3.column_dimensions['B'].width = 16

    return _build_excel_response(wb, '财务数据导入模板.xlsx')


# ── Kingdee 部门明细表 format detection ──────────────────────────────────────

_KD_ACCT_KW   = ['科目名称', '科目全称', '一级科目名称', '一级科目']
_KD_DEPT_KW   = ['部门']
_KD_DEBIT_KW  = ['本期借方', '借方发生额', '本期发生(借', '发生额(借', '本月发生额(借']
_KD_CREDIT_KW = ['本期贷方', '贷方发生额', '本期发生(贷', '发生额(贷', '本月发生额(贷']
_KD_AMT_KW    = ['本期金额', '本月发生额', '发生额合计', '本年金额']
_KD_L3_KW     = ['明细科目', '三级科目', '科目明细', '子目', '小科目']
_KD_SKIP_KW   = ['合计', '小计', '总计', '期末', '期初', '余额', '科目代码', '科目编码', '编码']
# 核算维度明细账中的小计/汇总行摘要（非业务发生额，解析时跳过）
_LEDGER_SUMMARY_ROWS = {'期初余额', '本期合计', '本年累计', '期末余额'}

# ── 金蝶科目编码 → KXT 一级科目映射（核算维度明细账 / 部门明细表）──────────────
# 按科目编码前缀（第一段）归类到 KXT 一级科目
_KD_CODE_L1 = {
    '6001': '主营业务收入', '6051': '主营业务收入',
    '6301': '营业外收入',
    '6401': '主营业务成本', '6402': '主营业务成本',
    '6403': '税金成本',
    '6601': '销售费用',
    '6602': '管理费用',
    '6603': '财务费用',
    '6711': '营业外支出',
}
# 科目名称精确包含覆盖（优先于编码前缀）——集团管理费用在金蝶里挂在 6602 管理费用下，
# 但 KXT 体系中需单列以正确推算经营净利。
_KD_NAME_L1 = {
    '集团管理费用': '集团管理费用',
}
# ── 利润表行项目 → KXT 一级科目映射（金蝶 SpreadJS JSON 导出）──────────────────
# key 为去除「一、其中：加：减：」等前缀后的标准行名
_PL_ITEM_L1 = {
    '营业收入': '主营业务收入',
    '营业成本': '主营业务成本',
    '税金及附加': '税金成本',
    '销售费用': '销售费用',
    '管理费用': '管理费用',
    '财务费用': '财务费用',
    '营业外收入': '营业外收入',
    '营业外支出': '营业外支出',
}


def _detect_kingdee_format(ws):
    """Scan first 12 rows for Kingdee-style headers.
    Returns (data_start_row, col_map) or (None, {}).
    col_map keys: account, dept, debit(opt), credit(opt), amount(opt), l3(opt)
    """
    def hit(val, kws):
        return any(k in val for k in kws)

    for ri in range(1, min(13, ws.max_row + 1)):
        cm = {}
        for ci in range(1, min(ws.max_column + 1, 40)):
            v = str(ws.cell(row=ri, column=ci).value or '').strip()
            if not v:
                continue
            if 'account' not in cm and hit(v, _KD_ACCT_KW):
                cm['account'] = ci
            elif 'dept' not in cm and hit(v, _KD_DEPT_KW):
                cm['dept'] = ci
            elif 'debit' not in cm and hit(v, _KD_DEBIT_KW):
                cm['debit'] = ci
            elif 'credit' not in cm and hit(v, _KD_CREDIT_KW):
                cm['credit'] = ci
            elif 'amount' not in cm and hit(v, _KD_AMT_KW):
                cm['amount'] = ci
            elif 'l3' not in cm and hit(v, _KD_L3_KW):
                cm['l3'] = ci
        has_amount = ('debit' in cm and 'credit' in cm) or 'amount' in cm
        if 'account' in cm and 'dept' in cm and has_amount:
            return ri + 1, cm
    return None, {}


def _parse_kingdee_rows(ws, data_start, cm, bu, l1_map, l2_map, l3_map):
    """Parse rows using detected Kingdee column map. Returns (parsed_rows, errors)."""
    errors = []
    parsed = []

    for ri in range(data_start, ws.max_row + 1):
        def cv(col):
            return str(ws.cell(row=ri, column=col).value or '').strip()

        def cn(col):
            try:
                return Decimal(str(ws.cell(row=ri, column=col).value or 0))
            except (InvalidOperation, TypeError):
                return Decimal(0)

        acct = cv(cm['account'])
        dept = cv(cm['dept'])

        if not acct and not dept:
            continue
        if not acct or any(k in acct for k in _KD_SKIP_KW):
            continue

        # Accounting direction: revenue (sign=+1) grows on credit; cost (sign=-1) grows on debit.
        # Formula: sign * (credit − debit) yields correct positive magnitude for normal entries
        # and naturally handles 红字 (negative debit/credit reversal entries).
        # Zero-amount rows are skipped below — do NOT abs() here so reversals reduce totals.
        if 'debit' in cm and 'credit' in cm:
            raw_net = cn(cm['credit']) - cn(cm['debit'])
        else:
            raw_net = cn(cm['amount'])

        if raw_net == 0:
            continue

        # Match L1: exact first, then partial (name-in-cell or cell-in-name)
        l1 = l1_map.get(acct)
        matched_name = acct
        if not l1:
            for name, cat in l1_map.items():
                if name in acct or acct in name:
                    l1 = cat
                    matched_name = name
                    break
        if not l1:
            errors.append(f'第{ri}行：科目"{acct}"未匹配到一级科目（已跳过）')
            continue
        if l1.is_calculated:
            continue

        l2 = None
        if dept:
            if dept not in l2_map:
                l2_obj = L2Category(business_unit=bu, name=dept, sort_order=len(l2_map))
                l2_obj.save()
                l2_map[dept] = l2_obj
            l2 = l2_map[dept]

        l3 = None
        l3_name = cv(cm['l3']) if 'l3' in cm else ''
        if l3_name:
            key = (l1.id, l3_name)
            if key not in l3_map:
                l3_obj = L3Category(
                    business_unit=bu, l1_category=l1,
                    name=l3_name, sort_order=len(l3_map),
                )
                l3_obj.save()
                l3_map[key] = l3_obj
            l3 = l3_map[key]

        # Apply accounting sign: revenue sign=+1 → amount=credit-debit; cost sign=-1 → amount=debit-credit
        amount = Decimal(str(l1.sign)) * raw_net

        parsed.append({
            'l1': l1, 'l2': l2, 'l3': l3, 'amount': amount,
            'l1_name': matched_name, 'l2_name': dept, 'l3_name': l3_name,
        })

    return parsed, errors


# ── 金蝶 核算维度明细账（部门明细表）解析 ─────────────────────────────────────

def _detect_dept_ledger(ws):
    """Detect Kingdee 核算维度明细账 layout. Returns (data_start, col_map) or (None, {}).
    col_map keys: dept, code, name, debit, credit, summary
    """
    for ri in range(1, min(8, ws.max_row + 1)):
        cm = {}
        for ci in range(1, min(ws.max_column + 1, 20)):
            v = str(ws.cell(row=ri, column=ci).value or '').strip()
            if v == '部门名称':
                cm['dept'] = ci
            elif v == '科目编码':
                cm['code'] = ci
            elif v == '科目名称':
                cm['name'] = ci
            elif v == '摘要':
                cm['summary'] = ci
            elif v == '借方':
                cm['debit'] = ci
            elif v == '贷方':
                cm['credit'] = ci
        if all(k in cm for k in ('dept', 'name', 'debit', 'credit', 'summary')):
            return ri + 1, cm
    return None, {}


def _map_dept_ledger_l1(code, name, l1_map):
    """Map a 部门明细账 row to an L1 category. 科目名称 override → 编码前缀。
    Returns (L1Category|None, matched_name|None).
    """
    for kw, l1name in _KD_NAME_L1.items():
        if kw in name:
            return l1_map.get(l1name), l1name
    prefix = str(code).split('.')[0].strip()
    l1name = _KD_CODE_L1.get(prefix)
    if l1name:
        return l1_map.get(l1name), l1name
    return None, None


def _parse_dept_ledger_rows(ws, data_start, cm, bu, l1_map, l2_map, l3_map):
    """Parse Kingdee 核算维度明细账 by aggregating business transaction rows per account.

    Closed-period exports embed a 「结转损益」 carry-forward entry that reverses each
    account into the P&L, so the 「本期合计」 subtotal nets to ZERO for every account.
    We therefore sum the individual transaction rows and EXCLUDE 结转损益 (and the
    期初/合计/累计 summary rows) to recover the real period movement.
    部门名称 → L2, 科目名称 → L3, 编码前缀 → L1. Returns (parsed_rows, errors).
    """
    errors = []

    def _dec(ri, col):
        try:
            return Decimal(str(ws.cell(row=ri, column=col).value or 0))
        except (InvalidOperation, TypeError):
            return Decimal(0)

    # Sum (credit - debit) of business rows per (dept, code, name), preserving order.
    agg = {}
    order = []
    for ri in range(data_start, ws.max_row + 1):
        summ = str(ws.cell(row=ri, column=cm['summary']).value or '').strip()
        if summ in _LEDGER_SUMMARY_ROWS or '结转损益' in summ:
            continue
        code = str(ws.cell(row=ri, column=cm['code']).value or '').strip() if 'code' in cm else ''
        name = str(ws.cell(row=ri, column=cm['name']).value or '').strip()
        if not code and not name:
            continue
        dept = str(ws.cell(row=ri, column=cm['dept']).value or '').strip()
        key = (dept, code, name)
        if key not in agg:
            agg[key] = Decimal(0)
            order.append(key)
        agg[key] += _dec(ri, cm['credit']) - _dec(ri, cm['debit'])

    parsed = []
    for dept, code, name in order:
        raw_net = agg[(dept, code, name)]
        if raw_net == 0:
            continue

        l1, l1name = _map_dept_ledger_l1(code, name, l1_map)
        if not l1:
            errors.append(f'科目"{code} {name}"未匹配到一级科目（已跳过）')
            continue
        if l1.is_calculated:
            continue
        amount = Decimal(str(l1.sign)) * raw_net

        l2 = None
        if dept:
            if dept not in l2_map:
                obj = L2Category(business_unit=bu, name=dept, sort_order=len(l2_map))
                obj.save()
                l2_map[dept] = obj
            l2 = l2_map[dept]

        l3 = None
        if name:
            key = (l1.id, name)
            if key not in l3_map:
                obj = L3Category(business_unit=bu, l1_category=l1, name=name, sort_order=len(l3_map))
                obj.save()
                l3_map[key] = obj
            l3 = l3_map[key]

        parsed.append({
            'l1': l1, 'l2': l2, 'l3': l3, 'amount': amount,
            'l1_name': l1name, 'l2_name': dept, 'l3_name': name,
        })

    return parsed, errors


# ── 金蝶 利润表 SpreadJS JSON 解析 ───────────────────────────────────────────

def _strip_pl_prefix(name):
    """Strip 一、二、…/（一）/其中：/加：/减： prefixes from a P&L line label."""
    s = str(name).strip()
    s = re.sub(r'^[一二三四五六七八九十]+、', '', s)
    s = re.sub(r'^（[一二三四五六七八九十]+）', '', s)
    for p in ('其中：', '加：', '减：', '其中:', '加:', '减:'):
        if s.startswith(p):
            s = s[len(p):]
    return s.strip()


def _parse_kingdee_pl_json(data_str, l1_map):
    """Parse a Kingdee/SpreadJS workbook JSON and extract the 利润表 sheet.
    Returns (pl_data {l1_name: Decimal}, errors).
    """
    try:
        wb = json.loads(data_str)
    except json.JSONDecodeError as e:
        return {}, [f'JSON 解析失败：{e}']
    sheets = wb.get('sheets') if isinstance(wb, dict) else None
    if not isinstance(sheets, dict):
        return {}, ['未识别的 JSON 结构（缺少 sheets 节点）']

    pl_sheet = next((sh for nm, sh in sheets.items() if '利润' in nm), None)
    if pl_sheet is None:
        return {}, ['JSON 中未找到「利润表」工作表']

    dt = (pl_sheet.get('data') or {}).get('dataTable') or {}

    pl_data = {}
    rev_total = cost_total = None
    for r_key in sorted(dt, key=lambda k: int(k) if str(k).isdigit() else 0):
        row = dt[r_key]
        c0 = (row.get('0') or {}).get('value')
        c1 = (row.get('1') or {}).get('value')
        if c0 is None:
            continue
        label = _strip_pl_prefix(c0)
        try:
            amt = Decimal(str(c1))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if label == '营业总收入':
            rev_total = amt
        elif label == '营业总成本':
            cost_total = amt
        l1name = _PL_ITEM_L1.get(label)
        if l1name and l1name in l1_map:
            pl_data.setdefault(l1name, amt)

    # Fall back to 营业总收入/成本 if the 「其中」 detail lines are absent
    if '主营业务收入' not in pl_data and rev_total is not None:
        pl_data['主营业务收入'] = rev_total
    if '主营业务成本' not in pl_data and cost_total is not None:
        pl_data['主营业务成本'] = cost_total

    return pl_data, []


def _parse_template_rows(ws, bu, l1_map, l2_map, l3_map):
    """Parse the KXT 5-column template format (L1 / L2 / L3 / 借方 / 贷方).
    Also accepts the legacy 4-column format (L1 / L2 / L3 / 金额) for backward compatibility.
    """
    errors = []
    parsed = []

    # Detect old 4-column vs new 5-column format from header row
    h4 = str(ws.cell(row=1, column=4).value or '').strip()
    h5 = str(ws.cell(row=1, column=5).value or '').strip()
    five_col = bool(h5)  # if column 5 has a header it's the new format

    def _to_dec(val):
        try:
            return Decimal(str(val))
        except (InvalidOperation, TypeError):
            return Decimal(0)

    for ri in range(2, ws.max_row + 1):
        l1_name = str(ws.cell(row=ri, column=1).value or '').strip()
        l2_name = str(ws.cell(row=ri, column=2).value or '').strip()
        l3_name = str(ws.cell(row=ri, column=3).value or '').strip()

        if five_col:
            debit_raw = ws.cell(row=ri, column=4).value
            credit_raw = ws.cell(row=ri, column=5).value
            if not l1_name and debit_raw is None and credit_raw is None:
                continue
        else:
            amt_raw = ws.cell(row=ri, column=4).value
            if not l1_name and amt_raw is None:
                continue

        if not l1_name:
            errors.append(f'第{ri}行：一级科目不能为空')
            continue
        if l1_name not in l1_map:
            errors.append(f'第{ri}行：一级科目"{l1_name}"不存在，请先在设置中添加')
            continue
        l1 = l1_map[l1_name]
        if l1.is_calculated:
            continue

        # Compute amount using accounting direction (same as Kingdee parser)
        if five_col:
            debit = _to_dec(debit_raw)
            credit = _to_dec(credit_raw)
            raw_net = credit - debit
        else:
            # Legacy format: positive amount supplied directly (no sign adjustment needed)
            try:
                raw_net = Decimal(str(ws.cell(row=ri, column=4).value))
                # For backward compat: assume amount already represents the correct magnitude
                # (revenue positive, cost positive). Convert to sign * (credit-debit) space:
                # amount = sign * raw_net / sign = raw_net, so just use raw_net directly.
                # We still apply sign so totals are consistent: sign * raw_net / sign = raw_net / 1
                # Actually for legacy we store raw_net directly without sign adjustment.
                amount = raw_net
            except (InvalidOperation, TypeError):
                errors.append(f'第{ri}行：金额格式错误')
                continue
            l2 = None
            l3 = None
            if l2_name:
                if l2_name not in l2_map:
                    l2_obj = L2Category(business_unit=bu, name=l2_name, sort_order=len(l2_map))
                    l2_obj.save()
                    l2_map[l2_name] = l2_obj
                l2 = l2_map[l2_name]
            if l3_name:
                key = (l1.id, l3_name)
                if key not in l3_map:
                    l3_obj = L3Category(business_unit=bu, l1_category=l1, name=l3_name, sort_order=len(l3_map))
                    l3_obj.save()
                    l3_map[key] = l3_obj
                l3 = l3_map[key]
            parsed.append({'l1': l1, 'l2': l2, 'l3': l3, 'amount': amount,
                           'l1_name': l1_name, 'l2_name': l2_name, 'l3_name': l3_name})
            continue

        # Five-column path: apply accounting direction
        amount = Decimal(str(l1.sign)) * raw_net

        l2 = None
        l3 = None
        if l2_name:
            if l2_name not in l2_map:
                l2_obj = L2Category(business_unit=bu, name=l2_name, sort_order=len(l2_map))
                l2_obj.save()
                l2_map[l2_name] = l2_obj
            l2 = l2_map[l2_name]
        if l3_name:
            key = (l1.id, l3_name)
            if key not in l3_map:
                l3_obj = L3Category(business_unit=bu, l1_category=l1, name=l3_name, sort_order=len(l3_map))
                l3_obj.save()
                l3_map[key] = l3_obj
            l3 = l3_map[key]

        parsed.append({
            'l1': l1, 'l2': l2, 'l3': l3, 'amount': amount,
            'l1_name': l1_name, 'l2_name': l2_name, 'l3_name': l3_name,
        })

    return parsed, errors


def _parse_profit_loss_rows(ws, l1_map):
    """Parse 利润表 (P&L statement) in standard 2-column format: 科目名称 + 本期金额.
    Returns dict {l1_name: Decimal(amount)}.
    """
    result = {}
    for ri in range(2, ws.max_row + 1):
        name = str(ws.cell(row=ri, column=1).value or '').strip()
        amt_raw = ws.cell(row=ri, column=2).value
        if not name:
            continue
        # Flexible name matching against L1 categories
        matched = l1_map.get(name)
        if not matched:
            for k in l1_map:
                if k in name or name in k:
                    matched = l1_map[k]
                    name = k
                    break
        if not matched:
            continue
        try:
            result[name] = Decimal(str(amt_raw))
        except (InvalidOperation, TypeError):
            pass
    return result


def _parse_json_rows(data_str, bu, l1_map, l2_map, l3_map):
    """Parse JSON array import. Each element: {l1, l2?, l3?, debit?, credit?, amount?}.
    Returns (parsed_rows, errors).
    """
    errors = []
    parsed = []
    try:
        rows = json.loads(data_str)
        if not isinstance(rows, list):
            return [], ['JSON 格式错误：根节点需为数组']
    except json.JSONDecodeError as e:
        return [], [f'JSON 解析失败：{e}']

    def _to_dec(v):
        try:
            return Decimal(str(v))
        except (InvalidOperation, TypeError):
            return Decimal(0)

    for i, row in enumerate(rows, 1):
        l1_name = str(row.get('l1', '')).strip()
        l2_name = str(row.get('l2', '')).strip()
        l3_name = str(row.get('l3', '')).strip()

        if not l1_name:
            errors.append(f'第{i}项：缺少 l1 字段')
            continue
        l1 = l1_map.get(l1_name)
        if not l1:
            for k, cat in l1_map.items():
                if k in l1_name or l1_name in k:
                    l1 = cat
                    l1_name = k
                    break
        if not l1:
            errors.append(f'第{i}项：l1="{l1_name}" 未匹配到一级科目')
            continue
        if l1.is_calculated:
            continue

        if 'amount' in row:
            amount = _to_dec(row['amount'])
        else:
            debit = _to_dec(row.get('debit', 0))
            credit = _to_dec(row.get('credit', 0))
            amount = Decimal(str(l1.sign)) * (credit - debit)

        l2 = None
        if l2_name:
            if l2_name not in l2_map:
                obj = L2Category(business_unit=bu, name=l2_name, sort_order=len(l2_map))
                obj.save()
                l2_map[l2_name] = obj
            l2 = l2_map[l2_name]

        l3 = None
        if l3_name:
            key = (l1.id, l3_name)
            if key not in l3_map:
                obj = L3Category(business_unit=bu, l1_category=l1, name=l3_name, sort_order=len(l3_map))
                obj.save()
                l3_map[key] = obj
            l3 = l3_map[key]

        parsed.append({
            'l1': l1, 'l2': l2, 'l3': l3, 'amount': amount,
            'l1_name': l1_name, 'l2_name': l2_name, 'l3_name': l3_name,
        })

    return parsed, errors


def _compute_pl_check(parsed_rows):
    """Compute P&L KPIs + L1/L2 summaries from uploaded rows for reconciliation display."""
    from collections import defaultdict

    raw = defaultdict(Decimal)
    l2_totals = defaultdict(lambda: defaultdict(Decimal))
    for r in parsed_rows:
        raw[r['l1_name']] += r['amount']
        l2_totals[r['l1_name']][r['l2_name'] or '（无项目部）'] += r['amount']

    l1_cats = list(L1Category.objects.order_by('sort_order', 'id').all())
    name_map = {}
    l1_summary = []

    for l1 in l1_cats:
        if l1.is_calculated:
            formula = _CALC_FORMULAS.get(l1.name)
            val = float(formula(name_map)) if formula else 0.0
        else:
            val = float(raw.get(l1.name, 0))
        name_map[l1.name] = val
        if val != 0 or l1.is_calculated:
            l1_summary.append({
                'name': l1.name, 'amount': round(val, 2),
                'is_calculated': l1.is_calculated,
            })

    l2_summary = []
    for l1_name, depts in l2_totals.items():
        for dept_name, amt in sorted(depts.items()):
            if float(amt) != 0:
                l2_summary.append({
                    'l1_name': l1_name,
                    'l2_name': dept_name,
                    'amount': round(float(amt), 2),
                })

    KPI_ORDER = ['主营业务收入', '主营业务成本', '运营毛利', '经营毛利', '经营净利']
    nm = {r['name']: r for r in l1_summary}
    kpis = [nm[k] for k in KPI_ORDER if k in nm]

    return {'kpis': kpis, 'l1_summary': l1_summary, 'l2_summary': l2_summary}


@cw_required()
def batch_upload(request):
    if request.method != 'POST':
        return err('方法不允许', 405)
    if not _can_upload(request):
        return err('权限不足', 403)

    bu = request.POST.get('bu', '').strip()
    year_str = request.POST.get('year', '').strip()
    month_str = request.POST.get('month', '').strip()

    if not bu:
        return err('请指定事业部')
    if bu not in VALID_BUSINESS_UNITS:
        return err(f'无效的事业部：{bu}')
    if not _can_access_bu(request, bu):
        return err('您无权为该事业部上传数据', 403)

    try:
        year = int(year_str)
        month = int(month_str)
        assert 2000 <= year <= 2100 and 1 <= month <= 12
    except Exception:
        return err('年份或月份无效')

    f = request.FILES.get('file')
    if not f:
        return err('请上传文件')
    if f.size > IMPORT_SIZE_LIMIT:
        return err(f'文件超过5MB限制（当前{f.size // 1024 // 1024}MB）')

    l1_map = {c.name: c for c in L1Category.objects.order_by('sort_order', 'id')}
    if not l1_map:
        return err('系统尚未配置一级科目，请先在「设置」中添加一级科目')

    fname = f.name.lower()
    l2_map = {c.name: c for c in L2Category.objects.filter(business_unit=bu)}
    l3_map = {(c.l1_category_id, c.name): c for c in L3Category.objects.filter(business_unit=bu)}

    # ── JSON：金蝶利润表（SpreadJS）= 利润表；旧版数组 = 部门明细 ─────────────────
    if fname.endswith('.json'):
        data_str = f.read().decode('utf-8', errors='replace')
        if data_str.lstrip().startswith('{'):
            # SpreadJS workbook → 利润表
            pl_data, errors = _parse_kingdee_pl_json(data_str, l1_map)
            if not pl_data:
                hint = '；'.join(errors[:2]) if errors else '未能从利润表JSON中读取到有效科目金额'
                return err(hint)
            parsed_rows = [
                {'l1': l1_map[n], 'l2': None, 'l3': None, 'amount': a,
                 'l1_name': n, 'l2_name': '', 'l3_name': ''}
                for n, a in pl_data.items() if n in l1_map and not l1_map[n].is_calculated
            ]
            batch_type = ImportBatch.TYPE_PL
            fmt = 'kingdee_pl_json'
        else:
            parsed_rows, errors = _parse_json_rows(data_str, bu, l1_map, l2_map, l3_map)
            batch_type = ImportBatch.TYPE_DEPT
            fmt = 'json'

    # ── Excel：金蝶核算维度明细账 / KXT模板 / 旧版利润表 = 部门明细 ─────────────────
    else:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(f, data_only=True)
            ws = wb.active
        except Exception:
            return err('文件格式错误，请使用Excel(.xlsx)格式')

        batch_type = ImportBatch.TYPE_DEPT
        ledger_start, ledger_cm = _detect_dept_ledger(ws)
        row1_vals = [str(ws.cell(row=1, column=c).value or '').strip() for c in range(1, 6)]
        is_kxt = (row1_vals[:5] == EXCEL_HEADERS or row1_vals[:4] == ['一级科目', '二级项目部', '三级科目明细', '金额(元)'])

        if ledger_start is not None:
            parsed_rows, errors = _parse_dept_ledger_rows(ws, ledger_start, ledger_cm, bu, l1_map, l2_map, l3_map)
            fmt = 'kingdee_ledger'
        elif is_kxt:
            parsed_rows, errors = _parse_template_rows(ws, bu, l1_map, l2_map, l3_map)
            fmt = 'template'
        else:
            data_start, cm = _detect_kingdee_format(ws)
            if data_start is None:
                return err(
                    '无法识别文件格式。支持：\n'
                    '① 金蝶核算维度明细账（部门明细表，含"部门名称""科目编码""借方""贷方"列）\n'
                    '② KXT模板（借方/贷方两列）\n'
                    '③ 金蝶利润表 JSON（.json 文件）'
                )
            parsed_rows, errors = _parse_kingdee_rows(ws, data_start, cm, bu, l1_map, l2_map, l3_map)
            fmt = 'kingdee'

    # Non-fatal warnings: show first 10 but don't block import
    warnings = errors[:10] if errors else []

    if not parsed_rows:
        hint = '；'.join(errors[:3]) if errors else '文件中没有有效数据行'
        return err(hint)

    # Compute P&L reconciliation preview (only meaningful for dept_detail uploads)
    pl_check = _compute_pl_check(parsed_rows) if batch_type == ImportBatch.TYPE_DEPT else {}

    # Create draft batch + entries atomically
    with transaction.atomic(using='default'):  # caiwu 已并入 default 主库(整合阶段1)
        batch = ImportBatch.objects.create(
            business_unit=bu, year=year, month=month,
            batch_type=batch_type,
            status=ImportBatch.STATUS_DRAFT,
            uploaded_by=request.pk_user,  # unified platform account (PaikuanUser)
            row_count=len(parsed_rows),
            file_name=f.name,
        )
        FinancialEntry.objects.bulk_create([
            FinancialEntry(batch=batch, l1=r['l1'], l2=r['l2'], l3=r['l3'], amount=r['amount'])
            for r in parsed_rows
        ])

    return ok({
        'batch': batch.to_dict(),
        'row_count': len(parsed_rows),
        'fmt': fmt,
        'warnings': warnings,
        'pl_check': pl_check,
    })


@cw_required()
def batch_publish(request, bid):
    if request.method != 'PUT':
        return err('方法不允许', 405)
    if not _can_publish(request):
        return err('权限不足', 403)
    try:
        batch = ImportBatch.objects.get(id=bid)
    except ImportBatch.DoesNotExist:
        return err('批次不存在', 404)
    if not _can_access_bu(request, batch.business_unit):
        return err('您无权操作该事业部数据', 403)
    if batch.status == ImportBatch.STATUS_PUBLISHED:
        return err('该批次已发布')

    # Use a transaction + row-level lock so concurrent publish requests for
    # the same BU+month don't both delete each other's data.
    with transaction.atomic(using='default'):  # caiwu 已并入 default 主库(整合阶段1)
        # Re-fetch with lock to guard against concurrent publish
        try:
            batch = ImportBatch.objects.select_for_update().get(id=bid)
        except ImportBatch.DoesNotExist:
            return err('批次不存在', 404)
        if batch.status == ImportBatch.STATUS_PUBLISHED:
            return err('该批次已发布')

        # Retire any previously published batch for same BU+month+type.
        # (部门明细表 and 利润表 coexist — only replace the same table type.)
        old_published = ImportBatch.objects.select_for_update().filter(
            business_unit=batch.business_unit,
            year=batch.year,
            month=batch.month,
            batch_type=batch.batch_type,
            status=ImportBatch.STATUS_PUBLISHED,
        )
        for old in old_published:
            old.entries.all().delete()
            old.delete()

        batch.status = ImportBatch.STATUS_PUBLISHED
        batch.published_at = timezone.now()
        batch.save()
    return ok(batch.to_dict())


@cw_required()
def batch_detail(request, bid):
    try:
        batch = ImportBatch.objects.get(id=bid)
    except ImportBatch.DoesNotExist:
        return err('批次不存在', 404)
    if not _can_access_bu(request, batch.business_unit):
        return err('无权访问', 403)

    if request.method == 'GET':
        return ok(batch.to_dict())

    if request.method == 'DELETE':
        if not _can_delete(request):
            return err('权限不足', 403)
        batch.entries.all().delete()
        batch.delete()
        return ok({'deleted': bid})

    return err('方法不允许', 405)


@cw_required()
def batch_submission_status(request):
    """GET /batches/submission-status?year=&month=
    Returns per-BU completion status: which of (部门明细表, 利润表) have been submitted/published.
    """
    if request.method != 'GET':
        return err('方法不允许', 405)
    year_s = request.GET.get('year', '').strip()
    month_s = request.GET.get('month', '').strip()
    try:
        year = int(year_s)
        month = int(month_s)
        assert 2000 <= year <= 2100 and 1 <= month <= 12
    except Exception:
        return err('年份或月份无效')

    # Visible BUs depend on role/job
    if request.pk_role in ('super_admin', 'manager') or request.pk_job == 'general_manager':
        bus = BUSINESS_UNITS
    else:
        bus = [b for b in (request.pk_depts or []) if b in VALID_BUSINESS_UNITS]

    # Fetch all batches for this period across visible BUs
    batches_qs = ImportBatch.objects.filter(
        business_unit__in=bus, year=year, month=month,
    ).values('business_unit', 'batch_type', 'status', 'id', 'uploaded_at', 'uploaded_by__name')

    # Build lookup: bu → {batch_type → {status, id, ...}}
    lookup = {bu: {} for bu in bus}
    for b in batches_qs:
        bu = b['business_unit']
        btype = b['batch_type']
        existing = lookup[bu].get(btype)
        # Keep the most recent / published one
        if existing is None or b['status'] == 'published':
            lookup[bu][btype] = {
                'id': b['id'],
                'status': b['status'],
                'uploaded_at': b['uploaded_at'].isoformat() if b['uploaded_at'] else None,
                'uploaded_by': b['uploaded_by__name'],
            }

    result = []
    for bu in bus:
        types = lookup[bu]
        dept_info = types.get(ImportBatch.TYPE_DEPT)
        pl_info = types.get(ImportBatch.TYPE_PL)
        complete = (
            dept_info is not None and dept_info['status'] == 'published' and
            pl_info is not None and pl_info['status'] == 'published'
        )
        result.append({
            'bu': bu,
            'department_detail': dept_info,
            'profit_loss': pl_info,
            'complete': complete,
        })

    return ok({'year': year, 'month': month, 'bus': result})


# ── report ───────────────────────────────────────────────────────────────────

def _get_published_batches(bu_list, year, month, batch_type=ImportBatch.TYPE_DEPT):
    """Return published ImportBatch objects for given BUs and period.

    Reports/charts aggregate the 部门明细表 (TYPE_DEPT) only — the 利润表 (TYPE_PL)
    is a reconciliation reference and must NOT be summed alongside it (double-count).
    Pass batch_type=None to include all types.
    """
    qs = ImportBatch.objects.filter(
        business_unit__in=bu_list,
        year=year, month=month,
        status=ImportBatch.STATUS_PUBLISHED,
    )
    if batch_type:
        qs = qs.filter(batch_type=batch_type)
    return qs


def _aggregate_report(batches_qs, level):
    """Return hierarchical report rows including calculated L1 rows."""
    from collections import defaultdict

    batch_ids = list(batches_qs.values_list('id', flat=True))
    if not batch_ids:
        return []

    l1_cats = list(L1Category.objects.order_by('sort_order', 'id').all())

    # Raw aggregation by l1_id
    raw_agg = (
        FinancialEntry.objects
        .filter(batch_id__in=batch_ids)
        .values('l1_id')
        .annotate(amount=Sum('amount'))
    )
    raw_by_id = {r['l1_id']: float(r['amount']) for r in raw_agg}

    # Compute all L1 amounts including calculated rows
    name_map, id_map = _compute_l1_name_map(l1_cats, raw_by_id)

    if level == 1:
        rows = []
        for l1 in l1_cats:
            amt = id_map.get(l1.id)
            if amt is None:
                continue
            rows.append({
                'l1_id': l1.id, 'l1_name': l1.name,
                'amount': amt, 'is_calculated': l1.is_calculated,
            })
        return rows

    # For levels 2/3: fetch raw l2/l3 breakdown; calculated rows have no children
    if level == 2:
        l2_agg = (
            FinancialEntry.objects
            .filter(batch_id__in=batch_ids)
            .values('l1_id', 'l2_id', 'l2__name')
            .annotate(amount=Sum('amount'))
        )
        l1_children = defaultdict(list)
        for r in l2_agg:
            l1_children[r['l1_id']].append({
                'l2_id': r['l2_id'],
                'l2_name': r['l2__name'] or '（无项目部）',
                'amount': float(r['amount']),
            })

        rows = []
        for l1 in l1_cats:
            amt = id_map.get(l1.id)
            if amt is None:
                continue
            rows.append({
                'l1_id': l1.id, 'l1_name': l1.name,
                'amount': amt, 'is_calculated': l1.is_calculated,
                'children': [] if l1.is_calculated else sorted(
                    l1_children.get(l1.id, []), key=lambda x: x['l2_name'],
                ),
            })
        return rows

    if level == 3:
        l3_agg = (
            FinancialEntry.objects
            .filter(batch_id__in=batch_ids)
            .values('l1_id', 'l2_id', 'l2__name', 'l3_id', 'l3__name')
            .annotate(amount=Sum('amount'))
        )
        l2_totals = defaultdict(Decimal)
        l3_rows = defaultdict(list)
        l2_meta = {}
        for r in l3_agg:
            key = (r['l1_id'], r['l2_id'])
            l2_totals[key] += r['amount']
            l2_meta[key] = r['l2__name']
            l3_rows[key].append({
                'l3_id': r['l3_id'],
                'l3_name': r['l3__name'] or '（无明细）',
                'amount': float(r['amount']),
            })

        rows = []
        for l1 in l1_cats:
            amt = id_map.get(l1.id)
            if amt is None:
                continue
            if l1.is_calculated:
                children = []
            else:
                children = []
                for key, tot in l2_totals.items():
                    if key[0] != l1.id:
                        continue
                    l2_id = key[1]
                    children.append({
                        'l2_id': l2_id,
                        'l2_name': l2_meta.get(key) or '（无项目部）',
                        'amount': float(tot),
                        'children': l3_rows[key],
                    })
            rows.append({
                'l1_id': l1.id, 'l1_name': l1.name,
                'amount': amt, 'is_calculated': l1.is_calculated,
                'children': children,
            })
        return rows

    return []


def _l1_trend(bu_list, year, month, n=6):
    """每个一级科目最近 n 个月的金额序列（含计算行），用于报表行内迷你趋势线。

    返回 (trend_map, mom_map)：
      trend_map[l1_name] = [oldest … newest]，长度 n，缺失月补 0.0；
      mom_map[l1_name]   = 最新月对上月的环比百分比（上月为 0 或缺失时 None）。
    """
    from collections import defaultdict
    seq = []
    yy, mm = year, month
    for _ in range(n):
        seq.append((yy, mm))
        mm -= 1
        if mm == 0:
            mm, yy = 12, yy - 1
    seq.reverse()  # oldest → newest

    trend = defaultdict(lambda: [0.0] * n)
    for idx, (yy, mm) in enumerate(seq):
        rws = _aggregate_report(_get_published_batches(bu_list, yy, mm), 1)
        for r in rws:
            trend[r['l1_name']][idx] = float(r['amount'])

    mom = {}
    for name, series in trend.items():
        prev = series[-2] if len(series) >= 2 else 0.0
        mom[name] = round((series[-1] - prev) / abs(prev) * 100, 1) if prev else None
    return trend, mom


@cw_required()
def report(request):
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'report')
    if denied:
        return denied

    year_s = request.GET.get('year', '')
    month_s = request.GET.get('month', '')
    bu_param = request.GET.get('bu', '')
    try:
        level = int(request.GET.get('level', '1'))
        assert level in (1, 2, 3)
    except Exception:
        level = 1

    # Clamp drill-down to what this job may view.
    if level >= 3 and not _can_view(request, 'report_l3'):
        level = 2
    if level >= 2 and not _can_view(request, 'report_l2'):
        level = 1

    try:
        year = int(year_s)
        month = int(month_s)
        assert 2000 <= year <= 2100 and 1 <= month <= 12
    except Exception:
        return err('年份或月份无效')

    # Determine accessible BUs
    if request.pk_role == 'super_admin':
        accessible = BUSINESS_UNITS
    else:
        accessible = [d for d in request.pk_depts if d in VALID_BUSINESS_UNITS]

    if bu_param:
        if bu_param not in accessible:
            return err('无权访问该事业部', 403)
        bu_list = [bu_param]
    else:
        bu_list = accessible

    batches_qs = _get_published_batches(bu_list, year, month)
    rows = _aggregate_report(batches_qs, level)
    # Use 经营净利 as headline total; fall back to sum of raw rows
    profit_row = next((r for r in rows if r['l1_name'] == '经营净利'), None)
    total = profit_row['amount'] if profit_row else sum(
        (r['amount'] for r in rows if not r.get('is_calculated')), Decimal(0)
    )
    total_label = '经营净利' if profit_row else '合计金额'

    # Previous month KPIs for MoM comparison (level=1 only, lightweight)
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    prev_batches = _get_published_batches(bu_list, prev_year, prev_month)
    prev_rows_l1 = _aggregate_report(prev_batches, 1)
    prev_kpis = {r['l1_name']: float(r['amount']) for r in prev_rows_l1}

    # 行内环比 + 迷你趋势线：为每个顶层（一级科目）行附 mom/trend（含计算行）
    trend_map, mom_map = _l1_trend(bu_list, year, month, 6)
    for r in rows:
        r['mom'] = mom_map.get(r['l1_name'])
        r['trend'] = trend_map.get(r['l1_name'])

    return ok({
        'rows': rows, 'total': float(total), 'total_label': total_label,
        'level': level, 'year': year, 'month': month, 'bu': bu_param or None,
        'prev_kpis': prev_kpis, 'prev_year': prev_year, 'prev_month': prev_month,
    })


@cw_required()
def report_export(request):
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'report')
    if denied:
        return denied
    if not _can_view(request, 'export'):
        return err('无导出权限', 403, 403)

    year_s = request.GET.get('year', '')
    month_s = request.GET.get('month', '')
    bu_param = request.GET.get('bu', '')
    try:
        level = int(request.GET.get('level', '1'))
        assert level in (1, 2, 3)
    except Exception:
        level = 1

    if level >= 3 and not _can_view(request, 'report_l3'):
        level = 2
    if level >= 2 and not _can_view(request, 'report_l2'):
        level = 1

    try:
        year = int(year_s)
        month = int(month_s)
        assert 2000 <= year <= 2100 and 1 <= month <= 12
    except Exception:
        return err('年份或月份无效')

    if request.pk_role == 'super_admin':
        accessible = BUSINESS_UNITS
    else:
        accessible = [d for d in request.pk_depts if d in VALID_BUSINESS_UNITS]

    if bu_param:
        if bu_param not in accessible:
            return err('无权访问该事业部', 403)
        bu_list = [bu_param]
    else:
        bu_list = accessible

    batches_qs = _get_published_batches(bu_list, year, month)
    rows = _aggregate_report(batches_qs, level)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return err('服务器缺少 openpyxl 依赖')

    wb = openpyxl.Workbook()
    ws = wb.active
    level_label = {1: '一级', 2: '二级', 3: '三级'}[level]
    ws.title = f'{year}年{month}月{level_label}报表'

    header_fill = PatternFill(start_color='C96342', end_color='C96342', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True)

    if level == 1:
        headers = ['一级科目', '金额(元)']
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.fill = header_fill
            cell.font = header_font
        for row in rows:
            ws.append([row['l1_name'], float(row['amount'])])
    elif level == 2:
        headers = ['一级科目', '二级项目部', '金额(元)']
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.fill = header_fill
            cell.font = header_font
        for row in rows:
            ws.append([row['l1_name'], '', float(row['amount'])])
            for child in row.get('children', []):
                ws.append(['', child['l2_name'], float(child['amount'])])
    else:
        headers = ['一级科目', '二级项目部', '三级科目明细', '金额(元)']
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.fill = header_fill
            cell.font = header_font
        for row in rows:
            ws.append([row['l1_name'], '', '', float(row['amount'])])
            for l2 in row.get('children', []):
                ws.append(['', l2['l2_name'], '', float(l2['amount'])])
                for l3 in l2.get('children', []):
                    ws.append(['', '', l3['l3_name'], float(l3['amount'])])

    bu_label = bu_param or '全部事业部'
    filename = f'财务报表_{bu_label}_{year}年{month}月_{level_label}.xlsx'
    return _build_excel_response(wb, filename)


# ── 指标管理 & 财务驾驶舱 ──────────────────────────────────────────────────────
#
# Headline metrics are revenue (主营业务收入) and profit (经营净利). Targets are
# entered manually (FinancialTarget); actuals come from the aggregated, published
# 部门明细表. month=0 holds the annual target; 1-12 hold monthly targets.

REVENUE_L1 = '主营业务收入'
PROFIT_L1 = '经营净利'
GROSS_PROFIT_L1 = '经营毛利'


def _collect_actuals(bu_list, years):
    """Pull all published 部门明细表 actuals in ONE grouped query.

    Returns {(business_unit, year, month): name_map}, where name_map maps each L1
    category name → float (calculated rows like 经营净利 included). Periods/BUs with
    no published entries are simply absent. This replaces the per-BU/per-period
    _aggregate_report fan-out (dozens of round-trips) with a single query plus one
    L1Category fetch, so metrics/cockpit run in ~3 queries instead of ~50-90.
    """
    from collections import defaultdict
    agg = (
        FinancialEntry.objects
        .filter(
            batch__status=ImportBatch.STATUS_PUBLISHED,
            batch__batch_type=ImportBatch.TYPE_DEPT,
            batch__business_unit__in=bu_list,
            batch__year__in=list(years),
        )
        .values('batch__business_unit', 'batch__year', 'batch__month', 'l1_id')
        .annotate(amount=Sum('amount'))
    )
    raw = defaultdict(dict)
    for r in agg:
        key = (r['batch__business_unit'], r['batch__year'], r['batch__month'])
        raw[key][r['l1_id']] = float(r['amount'])

    l1_cats = list(L1Category.objects.order_by('sort_order', 'id'))
    out = {}
    for key, raw_by_id in raw.items():
        name_map, _ = _compute_l1_name_map(l1_cats, raw_by_id)
        out[key] = name_map
    return out


def _rp(actuals, bu, year, month):
    """(revenue, profit, gross_profit) for one BU/period from the actuals map."""
    nm = actuals.get((bu, year, month))
    if not nm:
        return None, None, None
    return nm.get(REVENUE_L1), nm.get(PROFIT_L1), nm.get(GROSS_PROFIT_L1)


def _period_group(actuals, bus, year, month):
    """(revenue, profit, gross_profit) summed across BUs for one period."""
    tuples = [_rp(actuals, bu, year, month) for bu in bus]
    rev   = _sum_opt([t[0] for t in tuples])
    prof  = _sum_opt([t[1] for t in tuples])
    gross = _sum_opt([t[2] for t in tuples])
    return rev, prof, gross


def _prev_period(year, month):
    """Calendar month before (year, month)."""
    return (year, month - 1) if month > 1 else (year - 1, 12)


def _rate(actual, target):
    """Achievement rate (%), rounded; None if not computable.

    使用 (1 + (actual - target)/|target|) * 100：
    - 目标为正时与 actual/target*100 完全等价（向后兼容）；
    - 目标为负（计划性亏损）时方向正确——实际亏损更小/转盈 → 达成率更高，
      实际亏损更大 → 达成率更低，不再出现 actual/target 因负负得正导致的反向；
    - 实际为负而目标为正时得到负达成率，如实反映"不仅没达标还亏损"。
    """
    if target in (None, 0) or actual is None:
        return None
    return round((1 + (actual - target) / abs(float(target))) * 100, 1)


def _chg(cur, prev):
    """Percent change cur vs prev; None when prev is missing or zero."""
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def _accessible_bus(request):
    if request.pk_role == 'super_admin':
        return list(BUSINESS_UNITS)
    return [d for d in request.pk_depts if d in VALID_BUSINESS_UNITS]


def _resolve_bu_list(request, bu_param):
    """(bu_list, error_response). bu_param empty → all accessible BUs."""
    accessible = _accessible_bus(request)
    if bu_param:
        if bu_param not in accessible:
            return None, err('无权访问该事业部', 403)
        return [bu_param], None
    return accessible, None


def _parse_year_month(request):
    year = int(request.GET.get('year', ''))
    month = int(request.GET.get('month', ''))
    assert 2000 <= year <= 2100 and 1 <= month <= 12
    return year, month


def _metric_block(target_rev, actual_rev, target_prof, actual_prof,
                  target_gross=None, actual_gross=None,
                  rev_prev=None, prof_prev=None, gross_prev=None,
                  rev_yoy=None, prof_yoy=None, gross_yoy=None,
                  with_chg=False):
    """Assemble one revenue/profit metric block: target, actual, rate, and
    (when with_chg) MoM/YoY change keys — always present for a uniform shape."""
    block = {
        'target_revenue': float(target_rev) if target_rev is not None else 0.0,
        'actual_revenue': actual_rev,
        'revenue_rate': _rate(actual_rev, target_rev),
        'target_profit': float(target_prof) if target_prof is not None else 0.0,
        'actual_profit': actual_prof,
        'profit_rate': _rate(actual_prof, target_prof),
        'target_gross_profit': float(target_gross) if target_gross is not None else 0.0,
        'actual_gross_profit': actual_gross,
        'gross_profit_rate': _rate(actual_gross, target_gross),
    }
    if with_chg:
        block['revenue_mom'] = _chg(actual_rev, rev_prev)
        block['profit_mom'] = _chg(actual_prof, prof_prev)
        block['gross_profit_mom'] = _chg(actual_gross, gross_prev)
        block['revenue_yoy'] = _chg(actual_rev, rev_yoy)
        block['profit_yoy'] = _chg(actual_prof, prof_yoy)
        block['gross_profit_yoy'] = _chg(actual_gross, gross_yoy)
    return block


def _bu_metrics(bu, year, month, tgt_index, actuals):
    """Full metric bundle (month block + YTD block) for one BU, from the
    pre-collected actuals map (no per-BU DB round-trips)."""
    prev_year, prev_month = _prev_period(year, month)

    rev_m,  prof_m,  gross_m  = _rp(actuals, bu, year, month)
    rev_pm, prof_pm, gross_pm = _rp(actuals, bu, prev_year, prev_month)
    rev_ym, prof_ym, gross_ym = _rp(actuals, bu, year - 1, month)
    # YTD = sum of monthly actuals Jan..month (revenue/profit/gross all additive).
    rev_ytd   = _sum_opt([_rp(actuals, bu, year, m)[0] for m in range(1, month + 1)])
    prof_ytd  = _sum_opt([_rp(actuals, bu, year, m)[1] for m in range(1, month + 1)])
    gross_ytd = _sum_opt([_rp(actuals, bu, year, m)[2] for m in range(1, month + 1)])

    m_tgt = tgt_index.get((bu, month), {})
    a_tgt = tgt_index.get((bu, FinancialTarget.MONTH_ANNUAL), {})

    return {
        'business_unit': bu,
        'month': _metric_block(
            m_tgt.get('target_revenue'), rev_m,
            m_tgt.get('target_profit'), prof_m,
            target_gross=m_tgt.get('target_gross_profit'), actual_gross=gross_m,
            rev_prev=rev_pm, prof_prev=prof_pm, gross_prev=gross_pm,
            rev_yoy=rev_ym, prof_yoy=prof_ym, gross_yoy=gross_ym,
            with_chg=True),
        'ytd': _metric_block(
            a_tgt.get('target_revenue'), rev_ytd,
            a_tgt.get('target_profit'), prof_ytd,
            target_gross=a_tgt.get('target_gross_profit'), actual_gross=gross_ytd),
    }


def _sum_opt(values):
    """Sum treating None as 0; return None only if every value is None."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _aggregate_total(bu_blocks, key):
    """Build a group-total block by summing per-BU blocks for 'month' or 'ytd'."""
    rev_t   = _sum_opt([b[key]['target_revenue'] for b in bu_blocks])
    rev_a   = _sum_opt([b[key]['actual_revenue'] for b in bu_blocks])
    prof_t  = _sum_opt([b[key]['target_profit'] for b in bu_blocks])
    prof_a  = _sum_opt([b[key]['actual_profit'] for b in bu_blocks])
    gross_t = _sum_opt([b[key]['target_gross_profit'] for b in bu_blocks])
    gross_a = _sum_opt([b[key]['actual_gross_profit'] for b in bu_blocks])
    return {
        'target_revenue': rev_t or 0.0, 'actual_revenue': rev_a,
        'revenue_rate': _rate(rev_a, rev_t),
        'target_profit': prof_t or 0.0, 'actual_profit': prof_a,
        'profit_rate': _rate(prof_a, prof_t),
        'target_gross_profit': gross_t or 0.0, 'actual_gross_profit': gross_a,
        'gross_profit_rate': _rate(gross_a, gross_t),
    }


def _attach_group_chg(block, bus, year, month, actuals):
    """Add group-level MoM/YoY to a month total block (rates can't be summed, so
    recompute from consolidated actuals)."""
    prev_year, prev_month = _prev_period(year, month)
    rev_m,  prof_m,  gross_m  = _period_group(actuals, bus, year, month)
    rev_pm, prof_pm, gross_pm = _period_group(actuals, bus, prev_year, prev_month)
    rev_ym, prof_ym, gross_ym = _period_group(actuals, bus, year - 1, month)
    block['revenue_mom'] = _chg(rev_m, rev_pm)
    block['profit_mom'] = _chg(prof_m, prof_pm)
    block['gross_profit_mom'] = _chg(gross_m, gross_pm)
    block['revenue_yoy'] = _chg(rev_m, rev_ym)
    block['profit_yoy'] = _chg(prof_m, prof_ym)
    block['gross_profit_yoy'] = _chg(gross_m, gross_ym)
    return block


def _load_target_index(bus, year):
    """{(bu, month): {target_revenue, target_profit, target_gross_profit}} for the year."""
    idx = {}
    for t in FinancialTarget.objects.filter(business_unit__in=bus, year=year):
        idx[(t.business_unit, t.month)] = {
            'target_revenue': float(t.target_revenue),
            'target_profit': float(t.target_profit),
            'target_gross_profit': float(t.target_gross_profit),
        }
    return idx


@cw_required()
def targets(request):
    """GET ?year=&bu= → editable target rows; POST upsert a batch of targets."""
    denied = _page_denied(request, 'metrics')
    if denied:
        return denied

    if request.method == 'GET':
        try:
            year = int(request.GET.get('year', ''))
            assert 2000 <= year <= 2100
        except Exception:
            return err('年份无效')
        bus, e = _resolve_bu_list(request, request.GET.get('bu', ''))
        if e:
            return e
        rows = list(
            FinancialTarget.objects.filter(business_unit__in=bus, year=year)
            .order_by('business_unit', 'month')
        )
        return ok({'year': year, 'targets': [r.to_dict() for r in rows]})

    if request.method == 'POST':
        if not (request.pk_role == 'super_admin' or _can_upload(request)):
            return err('无录入权限', 403, 403)
        body = _parse_json(request)
        try:
            year = int(body.get('year'))
            assert 2000 <= year <= 2100
        except Exception:
            return err('年份无效')
        items = body.get('items') or []
        if not isinstance(items, list):
            return err('items 格式错误')

        accessible = _accessible_bus(request)
        uid = getattr(request, 'pk_uid', None)

        # ── parse all items first, then validate before touching the DB ────────
        parsed = []  # (bu, month, rev_dec, prof_dec)
        for it in items:
            bu = it.get('business_unit')
            if bu not in accessible:
                return err(f'无权编辑事业部：{bu}', 403)
            try:
                mo = int(it.get('month', 0))
                assert 0 <= mo <= 12
            except Exception:
                return err('月份无效')
            try:
                rev   = Decimal(str(it.get('target_revenue', 0) or 0))
                prof  = Decimal(str(it.get('target_profit', 0) or 0))
                gross = Decimal(str(it.get('target_gross_profit', 0) or 0))
            except (InvalidOperation, ValueError):
                return err('目标金额无效')
            parsed.append((bu, mo, rev, prof, gross))

        # ── month-sum == annual validation ────────────────────────────────────
        TOLERANCE = Decimal('1.00')
        from collections import defaultdict
        affected = {bu for bu, *_ in parsed}
        merged = defaultdict(dict)  # bu -> {month: (rev, prof, gross)}
        for t in FinancialTarget.objects.filter(year=year, business_unit__in=affected):
            merged[t.business_unit][t.month] = (
                t.target_revenue, t.target_profit, t.target_gross_profit)
        for bu, mo, rev, prof, gross in parsed:
            merged[bu][mo] = (rev, prof, gross)
        for bu, mp in merged.items():
            if 0 not in mp or any(m not in mp for m in range(1, 13)):
                continue
            for col, label in ((0, '收入'), (1, '经营净利'), (2, '经营毛利')):
                s = sum(mp[m][col] for m in range(1, 13))
                if abs(s - mp[0][col]) > TOLERANCE:
                    delta = float(s - mp[0][col]) / 10000
                    return err(f'{bu}：月度{label}目标合计与年度目标不符'
                               f'（差额 {delta:+.2f} 万元），请修正后保存')

        with transaction.atomic():
            for bu, mo, rev, prof, gross in parsed:
                FinancialTarget.objects.update_or_create(
                    business_unit=bu, year=year, month=mo,
                    defaults={
                        'target_revenue': rev, 'target_profit': prof,
                        'target_gross_profit': gross,
                        'updated_by_id': uid,
                    },
                )
        return ok({'saved': len(parsed)})

    return err('方法不允许', 405)


# ── Target template / upload / export ────────────────────────────────────────

_TGT_SECTIONS = [
    ('收入目标（万元）',    'target_revenue',      '收入'),
    ('经营毛利目标（万元）', 'target_gross_profit', '经营毛利'),
    ('经营净利目标（万元）', 'target_profit',       '经营净利'),
]
_MONTH_LABELS = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月']


def _build_target_wb(bus, year, existing_map):
    """Build an openpyxl workbook with 3 stacked sections (收入/净利/毛利).
    existing_map = {(bu, month): {target_revenue, target_profit, target_gross_profit}}
    For a blank template pass {} as existing_map.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = '指标模板'

    hdr_font  = Font(bold=True, color='FFFFFF', size=11)
    hdr_fill  = PatternFill('solid', fgColor='C96342')
    sub_font  = Font(bold=True, size=10)
    sub_fill  = PatternFill('solid', fgColor='F3E8E0')
    col_font  = Font(bold=True, size=9, color='555555')
    col_fill  = PatternFill('solid', fgColor='FAF3EF')
    thin      = Side(style='thin', color='DDDDDD')
    thin_bdr  = Border(left=thin, right=thin, top=thin, bottom=thin)
    center    = Alignment(horizontal='center', vertical='center')
    right_al  = Alignment(horizontal='right', vertical='center')

    row = 1
    # Year banner
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=15)
    c = ws.cell(row=row, column=1, value=f'{year} 年度经营指标（万元）')
    c.font = Font(bold=True, size=13); c.alignment = center
    row += 1

    for sect_label, _field, _short in _TGT_SECTIONS:
        # Section header
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=15)
        c = ws.cell(row=row, column=1, value=sect_label)
        c.font = sub_font; c.fill = sub_fill; c.alignment = center
        row += 1

        # Column header
        ws.cell(row=row, column=1, value='事业部').font = col_font
        ws.cell(row=row, column=1).fill = col_fill
        ws.cell(row=row, column=1).alignment = center
        for mi, lbl in enumerate(_MONTH_LABELS, 2):
            c = ws.cell(row=row, column=mi, value=lbl)
            c.font = col_font; c.fill = col_fill; c.alignment = center
        c = ws.cell(row=row, column=14, value='年度目标')
        c.font = col_font; c.fill = col_fill; c.alignment = center
        c = ws.cell(row=row, column=15, value='月合计')
        c.font = col_font; c.fill = col_fill; c.alignment = center
        row += 1

        # BU data rows
        for bu in bus:
            ws.cell(row=row, column=1, value=bu).font = Font(bold=True, size=10)
            ws.cell(row=row, column=1).alignment = Alignment(vertical='center')
            for mi in range(1, 13):
                val = existing_map.get((bu, mi), {}).get(_field)
                c = ws.cell(row=row, column=mi + 1,
                            value=round(val / 10000, 2) if val is not None else None)
                c.number_format = '#,##0.00'
                c.alignment = right_al
            annual_val = existing_map.get((bu, 0), {}).get(_field)
            c = ws.cell(row=row, column=14,
                        value=round(annual_val / 10000, 2) if annual_val is not None else None)
            c.number_format = '#,##0.00'; c.alignment = right_al
            # Month-sum formula
            col_start = get_column_letter(2)
            col_end   = get_column_letter(13)
            ws.cell(row=row, column=15,
                    value=f'=SUM({col_start}{row}:{col_end}{row})').number_format = '#,##0.00'
            ws.cell(row=row, column=15).alignment = right_al
            # Apply border to all cells in row
            for col in range(1, 16):
                ws.cell(row=row, column=col).border = thin_bdr
            row += 1

        row += 1  # blank separator

    # Column widths
    ws.column_dimensions['A'].width = 16
    for col in range(2, 14):
        ws.column_dimensions[get_column_letter(col)].width = 9
    ws.column_dimensions['N'].width = 10
    ws.column_dimensions['O'].width = 10

    return wb


@cw_required()
def targets_template(request):
    """GET ?year= → download blank Excel template for target entry."""
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'metrics')
    if denied:
        return denied
    try:
        year = int(request.GET.get('year', yearCST()))
        assert 2000 <= year <= 2100
    except Exception:
        return err('年份无效')
    bus, e = _resolve_bu_list(request, '')
    if e:
        return e
    wb = _build_target_wb(bus, year, {})
    return _build_excel_response(wb, f'{year}年指标模板.xlsx')


@cw_required()
def targets_export(request):
    """GET ?year= → export current targets as filled Excel."""
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'metrics')
    if denied:
        return denied
    try:
        year = int(request.GET.get('year', yearCST()))
        assert 2000 <= year <= 2100
    except Exception:
        return err('年份无效')
    bus, e = _resolve_bu_list(request, '')
    if e:
        return e
    rows = FinancialTarget.objects.filter(business_unit__in=bus, year=year)
    existing_map = {}
    for t in rows:
        existing_map[(t.business_unit, t.month)] = {
            'target_revenue': float(t.target_revenue),
            'target_profit': float(t.target_profit),
            'target_gross_profit': float(t.target_gross_profit),
        }
    wb = _build_target_wb(bus, year, existing_map)
    return _build_excel_response(wb, f'{year}年指标导出.xlsx')


@cw_required()
def targets_upload(request):
    """POST multipart/form-data: file=<xlsx> year=<int> → bulk upsert targets."""
    if request.method != 'POST':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'metrics')
    if denied:
        return denied
    if not (request.pk_role == 'super_admin' or _can_upload(request)):
        return err('无录入权限', 403, 403)

    try:
        year = int(request.POST.get('year', ''))
        assert 2000 <= year <= 2100
    except Exception:
        return err('年份无效')

    f = request.FILES.get('file')
    if not f:
        return err('缺少文件')
    if f.size > IMPORT_SIZE_LIMIT:
        return err('文件过大（超过 5 MB）')

    accessible = _accessible_bus(request)
    uid = getattr(request, 'pk_uid', None)

    try:
        from openpyxl import load_workbook
        wb = load_workbook(f, data_only=True)
        ws = wb.active
    except Exception as ex:
        return err(f'文件解析失败：{ex}')

    # Detect section boundaries: column A contains the section header keyword.
    section_map = {s[0]: s[1] for s in _TGT_SECTIONS}
    valid_bus = set(accessible)
    current_field = None
    parsed = {}  # {(bu, month): {field: Decimal}}

    for row in ws.iter_rows():
        a_val = str(row[0].value or '').strip()
        if a_val in section_map:
            current_field = section_map[a_val]
            continue
        if current_field is None or not a_val:
            continue
        bu = a_val
        if bu not in valid_bus or a_val in ('事业部', '月合计', '年合计'):
            continue
        if bu not in valid_bus:
            continue
        # Columns B-M = months 1-12, N = annual (month=0)
        slots = [(i + 1, row[i + 1]) for i in range(12)]  # (month 1-12, cell)
        slots.append((0, row[13] if len(row) > 13 else None))  # annual
        for month_no, cell in slots:
            if cell is None:
                continue
            try:
                wan_val = cell.value
                if wan_val is None:
                    amount = Decimal('0')
                else:
                    amount = Decimal(str(float(wan_val))) * 10000
            except (InvalidOperation, ValueError, TypeError):
                continue
            key = (bu, month_no)
            if key not in parsed:
                parsed[key] = {}
            parsed[key][current_field] = amount

    if not parsed:
        return err('未从文件中解析到任何有效数据，请确认使用正确的指标模板')

    # Validate sum == annual for each BU × metric
    TOLERANCE = Decimal('1.00')
    from collections import defaultdict
    merged = defaultdict(lambda: defaultdict(dict))  # {bu: {month: {field: val}}}
    existing_qs = FinancialTarget.objects.filter(
        year=year, business_unit__in=accessible)
    for t in existing_qs:
        merged[t.business_unit][t.month] = {
            'target_revenue': t.target_revenue,
            'target_profit': t.target_profit,
            'target_gross_profit': t.target_gross_profit,
        }
    for (bu, mo), fields in parsed.items():
        for field, val in fields.items():
            if bu not in merged or mo not in merged[bu]:
                merged[bu][mo] = {}
            merged[bu][mo][field] = val

    for bu, mp in merged.items():
        if 0 not in mp or any(m not in mp for m in range(1, 13)):
            continue
        for col_field, label in (
            ('target_revenue', '收入'),
            ('target_profit', '经营净利'),
            ('target_gross_profit', '经营毛利'),
        ):
            annual = mp[0].get(col_field, Decimal('0'))
            s = sum(mp[m].get(col_field, Decimal('0')) for m in range(1, 13))
            if annual != 0 and abs(s - annual) > TOLERANCE:
                delta = float(s - annual) / 10000
                return err(f'{bu}：月度{label}合计与年度目标不符（差额 {delta:+.2f} 万元）')

    # Upsert
    saved = 0
    with transaction.atomic():
        for (bu, mo), fields in parsed.items():
            if not fields:
                continue
            FinancialTarget.objects.update_or_create(
                business_unit=bu, year=year, month=mo,
                defaults={**fields, 'updated_by_id': uid},
            )
            saved += 1

    return ok({'saved': saved})


def yearCST():
    from django.utils import timezone
    import datetime
    now = timezone.now().astimezone(datetime.timezone(datetime.timedelta(hours=8)))
    return now.year


@cw_required()
def metrics(request):
    """Per-BU revenue/profit targets vs actuals with achievement, MoM and YoY."""
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'metrics')
    if denied:
        return denied
    try:
        year, month = _parse_year_month(request)
    except Exception:
        return err('年份或月份无效')

    bus, e = _resolve_bu_list(request, request.GET.get('bu', ''))
    if e:
        return e

    tgt_index = _load_target_index(bus, year)
    actuals = _collect_actuals(bus, {year, year - 1})
    bu_rows = [_bu_metrics(bu, year, month, tgt_index, actuals) for bu in bus]
    total = {
        'business_unit': '全集团',
        'month': _attach_group_chg(_aggregate_total(bu_rows, 'month'), bus, year, month, actuals),
        'ytd': _aggregate_total(bu_rows, 'ytd'),
    }
    return ok({'year': year, 'month': month, 'bus': bu_rows, 'total': total})


@cw_required()
def cockpit(request):
    """Group-level KPI overview + per-BU bars + 12-month trend (actual vs target)."""
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'cockpit')
    if denied:
        return denied
    try:
        year, month = _parse_year_month(request)
    except Exception:
        return err('年份或月份无效')

    bus, e = _resolve_bu_list(request, request.GET.get('bu', ''))
    if e:
        return e

    tgt_index = _load_target_index(bus, year)
    actuals = _collect_actuals(bus, {year, year - 1})
    bu_rows = [_bu_metrics(bu, year, month, tgt_index, actuals) for bu in bus]

    overview = {
        # Headline cards: consolidated targets/actuals/rates + group MoM/YoY.
        'month': _attach_group_chg(_aggregate_total(bu_rows, 'month'), bus, year, month, actuals),
        'ytd': _aggregate_total(bu_rows, 'ytd'),
    }

    # 12-month trend: group actual revenue/profit + group target lines per month.
    trend = []
    for mo in range(1, 13):
        rev_a, prof_a, gross_a = _period_group(actuals, bus, year, mo)
        rev_t   = _sum_opt([tgt_index.get((bu, mo), {}).get('target_revenue') for bu in bus])
        prof_t  = _sum_opt([tgt_index.get((bu, mo), {}).get('target_profit') for bu in bus])
        gross_t = _sum_opt([tgt_index.get((bu, mo), {}).get('target_gross_profit') for bu in bus])
        trend.append({
            'month': mo,
            'actual_revenue': rev_a, 'actual_profit': prof_a, 'actual_gross_profit': gross_a,
            'target_revenue': rev_t, 'target_profit': prof_t, 'target_gross_profit': gross_t,
            'has_data': rev_a is not None or prof_a is not None,
        })

    return ok({
        'year': year, 'month': month,
        'overview': overview,
        'bus': bu_rows,
        'trend': trend,
    })


def _fmt_rate(v):
    return '—' if v is None else f'{v:.1f}%'


def _fmt_signed_pct(v):
    return '—' if v is None else f'{"+" if v >= 0 else ""}{v:.1f}%'


def _build_cockpit_prompt(year, month, bus, bu_rows, ov_m, ov_y, actuals):
    """Compose the group-level cockpit analysis prompt from consolidated +
    per-BU metrics and the 12-month group trend."""
    L = []
    L.append('【全集团合并概览】')
    L.append(f'  当月收入：{_fmt_wan(ov_m["actual_revenue"])}'
             f'（达成率{_fmt_rate(ov_m["revenue_rate"])}，环比{_fmt_signed_pct(ov_m.get("revenue_mom"))}，'
             f'同比{_fmt_signed_pct(ov_m.get("revenue_yoy"))}）')
    L.append(f'  当月利润：{_fmt_wan(ov_m["actual_profit"])}'
             f'（达成率{_fmt_rate(ov_m["profit_rate"])}，环比{_fmt_signed_pct(ov_m.get("profit_mom"))}，'
             f'同比{_fmt_signed_pct(ov_m.get("profit_yoy"))}）')
    L.append(f'  年度累计收入：{_fmt_wan(ov_y["actual_revenue"])}（年度目标达成率{_fmt_rate(ov_y["revenue_rate"])}）')
    L.append(f'  年度累计利润：{_fmt_wan(ov_y["actual_profit"])}（年度目标达成率{_fmt_rate(ov_y["profit_rate"])}）')

    L.append('')
    L.append('【各事业部表现（当月 / 年度累计）】')
    shown = 0
    for r in bu_rows:
        m, y = r['month'], r['ytd']
        # Skip BUs with no published actuals at all — keeps the prompt focused.
        if m['actual_revenue'] is None and m['actual_profit'] is None \
                and y['actual_revenue'] is None and y['actual_profit'] is None:
            continue
        shown += 1
        L.append(
            f'  {r["business_unit"]}：'
            f'当月收入{_fmt_wan(m["actual_revenue"])}(达成{_fmt_rate(m["revenue_rate"])}，'
            f'环比{_fmt_signed_pct(m.get("revenue_mom"))}，同比{_fmt_signed_pct(m.get("revenue_yoy"))})；'
            f'当月利润{_fmt_wan(m["actual_profit"])}(达成{_fmt_rate(m["profit_rate"])})；'
            f'YTD收入{_fmt_wan(y["actual_revenue"])}(达成{_fmt_rate(y["revenue_rate"])})，'
            f'YTD利润{_fmt_wan(y["actual_profit"])}(达成{_fmt_rate(y["profit_rate"])})'
        )
    if shown == 0:
        L.append('  （所选范围内各事业部均无已发布数据）')

    L.append('')
    L.append('【近12个月全集团趋势（实际收入/实际利润）】')
    tr = []
    for mo in range(1, 13):
        rev_a, prof_a, _gross_a = _period_group(actuals, bus, year, mo)
        if rev_a is None and prof_a is None:
            continue
        tr.append(f'{mo}月:收入{_fmt_wan(rev_a)}/利润{_fmt_wan(prof_a)}')
    L.append('  ' + ('；'.join(tr) if tr else '无'))

    return f"""你正在为集团管理层解读 {year}年{month}月 的「财务驾驶舱」。以下是全集团及各事业部的经营数据（口径：已发布部门明细表，收入=主营业务收入，利润=经营净利；集团总部为成本中心，本身无收入）。

{chr(10).join(L)}

请站在全集团高度，输出一份综合、全面的经营分析报告，包含：

1. **集团经营总览**：本月与年度累计的整体经营态势——收入/利润规模、目标达成进度、环比同比趋势的综合研判。
2. **事业部横向对比**：识别领跑与掉队的事业部，分析达成率分化与利润贡献结构，指出谁是增长引擎、谁在拖累集团。
3. **目标达成与缺口**：结合当前节奏研判全年能否达标，量化关键缺口与达成压力最大的事业部。
4. **风险预警**：亏损或利润大幅下滑的事业部、异常波动、成本/费用异常、过度依赖单一事业部等系统性风险。
5. **战略与资源配置建议**：3-5条面向集团决策的具体建议（资源倾斜、整改重点、目标校准等）。

要求：专业、有数据支撑、有洞察，避免空话套话；分点清晰，适合集团领导决策参考，篇幅 800-1200 字。"""


_COCKPIT_AI_SYSTEM = (
    '你是集团CFO级别的资深财务与经营分析专家，擅长从全集团高度做综合诊断、'
    '事业部横向对比与战略建议，用中文专业作答。'
)


def _cockpit_ai_prepare(request):
    """Shared validation + prompt build for both cockpit AI endpoints.

    Returns ((messages, scope), None) on success, or (None, err_response)."""
    if not settings.DEEPSEEK_API_KEY:
        return None, err('AI 分析未配置（缺少 DEEPSEEK_API_KEY）', 503)

    body = _parse_json(request)
    try:
        year = int(body.get('year'))
        month = int(body.get('month'))
        assert 2000 <= year <= 2100 and 1 <= month <= 12
    except Exception:
        return None, err('年份或月份无效')

    bus, e = _resolve_bu_list(request, (body.get('bu') or '').strip())
    if e:
        return None, e

    tgt_index = _load_target_index(bus, year)
    actuals = _collect_actuals(bus, {year, year - 1})
    bu_rows = [_bu_metrics(bu, year, month, tgt_index, actuals) for bu in bus]
    if not any(b['month']['actual_revenue'] is not None or b['ytd']['actual_revenue'] is not None
               for b in bu_rows):
        return None, err(f'{year}年{month}月该范围内暂无已发布数据，无法进行AI分析')

    ov_m = _attach_group_chg(_aggregate_total(bu_rows, 'month'), bus, year, month, actuals)
    ov_y = _aggregate_total(bu_rows, 'ytd')
    prompt = _build_cockpit_prompt(year, month, bus, bu_rows, ov_m, ov_y, actuals)
    messages = [
        {'role': 'system', 'content': _COCKPIT_AI_SYSTEM},
        {'role': 'user', 'content': prompt},
    ]
    scope = '全集团' if len(bus) > 1 else (bus[0] if bus else '全集团')
    return (messages, scope), None


@cw_required()
def cockpit_ai_analysis(request):
    """POST /cockpit/ai-analysis — 全集团综合分析（一次性返回，用 PRO 模型）。"""
    if request.method != 'POST':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'cockpit')
    if denied:
        return denied
    prep, e = _cockpit_ai_prepare(request)
    if e:
        return e
    messages, scope = prep
    try:
        text = _deepseek_chat(messages, timeout=180,
                              model=settings.DEEPSEEK_PRO_MODEL, max_tokens=3200)
        return ok({'analysis': text, 'model': settings.DEEPSEEK_PRO_MODEL, 'scope': scope})
    except Exception as ex:
        logger.error(f'Cockpit AI error: {ex}')
        return err(f'AI分析服务暂时不可用，请稍后重试（{str(ex)[:80]}）', 503)


@cw_required()
def cockpit_ai_analysis_stream(request):
    """POST /cockpit/ai-analysis/stream — 全集团综合分析，SSE 流式逐字推送。

    先流推理过程(reasoning)、再流正文(answer)，让领导秒级看到进度，不再干等。
    数据校验/无权限/无数据/无APIKey 仍在开流前以普通 JSON 错误返回。"""
    if request.method != 'POST':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'cockpit')
    if denied:
        return denied
    prep, e = _cockpit_ai_prepare(request)
    if e:
        return e
    messages, scope = prep
    model = settings.DEEPSEEK_PRO_MODEL

    def gen():
        yield _sse_event({'type': 'meta', 'scope': scope, 'model': model})
        try:
            for kind, delta in _deepseek_stream(messages, model=model,
                                                max_tokens=3200, timeout=300):
                yield _sse_event({'type': kind, 'delta': delta})
            yield _sse_event({'type': 'done'})
        except Exception as ex:
            logger.error(f'Cockpit AI stream error: {ex}')
            yield _sse_event({'type': 'error', 'error': f'AI分析服务暂时不可用（{str(ex)[:80]}）'})

    resp = StreamingHttpResponse(gen(), content_type='text/event-stream')
    resp['Cache-Control'] = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'   # 关掉 nginx 缓冲，确保逐块下推
    return resp


# ── charts ───────────────────────────────────────────────────────────────────

@cw_required()
def chart_trend(request):
    """
    ?bu=&year=
    Returns 12-month trend for the selected BU/year.
    Aggregates by month: total revenue (first L1), total entries sum per month.
    Frontend decides which L1 to display.
    """
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'charts')
    if denied:
        return denied
    if not _can_view(request, 'chart_trend'):
        return err('无访问权限', 403, 403)

    bu = request.GET.get('bu', '').strip()
    year_s = request.GET.get('year', '')

    try:
        year = int(year_s)
        assert 2000 <= year <= 2100
    except Exception:
        return err('年份无效')

    if not bu:
        return err('请指定事业部')
    if not _can_access_bu(request, bu):
        return err('无权访问该事业部', 403)

    l1_cats = list(L1Category.objects.order_by('sort_order', 'id'))

    # For each month, get published batch and aggregate by L1 (including calculated rows)
    result = []
    for month in range(1, 13):
        batches_qs = _get_published_batches([bu], year, month)
        batch_ids = list(batches_qs.values_list('id', flat=True))
        if batch_ids:
            agg = (
                FinancialEntry.objects
                .filter(batch_id__in=batch_ids)
                .values('l1_id')
                .annotate(amount=Sum('amount'))
            )
            raw_by_id = {r['l1_id']: float(r['amount']) for r in agg}
            _, id_map = _compute_l1_name_map(l1_cats, raw_by_id)
            month_data = id_map
        else:
            month_data = {}
        result.append({
            'month': month,
            'has_data': bool(batch_ids),
            'by_l1': month_data,
        })

    return ok({
        'year': year,
        'bu': bu,
        'months': result,
        'l1_categories': [c.to_dict() for c in l1_cats],
    })


@cw_required()
def chart_waterfall(request):
    """
    ?bu=&year=&month=&compare_year=&compare_month=
    Factor analysis between two periods using is_profit_driver L1 categories.
    Returns waterfall chart data.
    """
    if request.method != 'GET':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'charts')
    if denied:
        return denied
    if not _can_view(request, 'chart_waterfall'):
        return err('无访问权限', 403, 403)

    bu = request.GET.get('bu', '').strip()
    year_s = request.GET.get('year', '')
    month_s = request.GET.get('month', '')
    cmp_year_s = request.GET.get('compare_year', year_s)
    cmp_month_s = request.GET.get('compare_month', '')

    if not bu:
        return err('请指定事业部')
    if not _can_access_bu(request, bu):
        return err('无权访问该事业部', 403)

    try:
        year = int(year_s)
        month = int(month_s)
        cmp_year = int(cmp_year_s)
        cmp_month = int(cmp_month_s)
        assert all(2000 <= y <= 2100 for y in (year, cmp_year))
        assert all(1 <= m <= 12 for m in (month, cmp_month))
    except Exception:
        return err('年份或月份无效')

    l1_cats = list(L1Category.objects.order_by('sort_order', 'id'))

    def _get_l1_totals(yr, mo):
        batches_qs = _get_published_batches([bu], yr, mo)
        batch_ids = list(batches_qs.values_list('id', flat=True))
        if not batch_ids:
            return {}, {}
        agg = (
            FinancialEntry.objects
            .filter(batch_id__in=batch_ids)
            .values('l1_id')
            .annotate(amount=Sum('amount'))
        )
        raw_by_id = {r['l1_id']: float(r['amount']) for r in agg}
        name_map, id_map = _compute_l1_name_map(l1_cats, raw_by_id)
        return name_map, id_map

    base_name_map, base_id_map = _get_l1_totals(cmp_year, cmp_month)
    curr_name_map, curr_id_map = _get_l1_totals(year, month)

    def _safe_sum(id_map, cats):
        # Signed sum of raw rows == 经营净利 by construction (revenue +1, cost -1).
        # Must apply sign, else costs would add to (instead of subtract from) profit.
        return sum((id_map.get(l1.id, 0) or 0) * l1.sign for l1 in cats if not l1.is_calculated)

    # Headline profit = 经营净利 if available; otherwise sum raw entries
    base_total = base_name_map.get('经营净利') if '经营净利' in base_name_map else _safe_sum(base_id_map, l1_cats)
    curr_total = curr_name_map.get('经营净利') if '经营净利' in curr_name_map else _safe_sum(curr_id_map, l1_cats)
    base_total = base_total or 0
    curr_total = curr_total or 0

    # Factor analysis: ALL raw L1 categories (not calculated rows) form a complete
    # bridge so base + Σdeltas == current exactly. is_profit_driver only flags
    # which to emphasise; every changed raw item must appear or the bridge breaks.
    drivers = [l1 for l1 in l1_cats if not l1.is_calculated]

    factors = []
    for l1 in drivers:
        base_v = base_id_map.get(l1.id) or 0
        curr_v = curr_id_map.get(l1.id) or 0
        raw_delta = curr_v - base_v
        profit_delta = raw_delta * l1.sign  # sign=-1 (cost) → cost increase → negative profit impact
        factors.append({
            'l1_id': l1.id,
            'name': l1.name,
            'base': round(base_v, 2),
            'current': round(curr_v, 2),
            'delta': round(profit_delta, 2),
            'is_driver': l1.is_profit_driver,
        })

    # Waterfall: base → factor deltas → current total
    waterfall = [
        {'name': f'{cmp_year}年{cmp_month}月', 'value': round(base_total, 2), 'type': 'base'},
    ]
    for f in factors:
        if f['delta'] != 0:  # skip zero-delta factors to reduce noise
            waterfall.append({
                'name': f['name'],
                'value': f['delta'],
                'type': 'increase' if f['delta'] >= 0 else 'decrease',
            })
    # Close the bridge: the headline total (经营净利) is a calculated row, while the
    # factor bars are signed deltas of the raw rows. With the standard taxonomy these
    # reconcile exactly, but stray raw categories outside 经营净利's formula leave a
    # residual — surface it as an explicit factor so base + Σfactors == current and the
    # last bar always lands on the terminal column instead of floating short of it.
    residual = round((curr_total - base_total) - sum(f['delta'] for f in factors), 2)
    if abs(residual) >= 0.01:
        waterfall.append({
            'name': '其他',
            'value': residual,
            'type': 'increase' if residual >= 0 else 'decrease',
        })
    waterfall.append({'name': f'{year}年{month}月', 'value': round(curr_total, 2), 'type': 'total'})

    return ok({
        'bu': bu,
        'base_period': {'year': cmp_year, 'month': cmp_month, 'total': base_total},
        'current_period': {'year': year, 'month': month, 'total': curr_total},
        'factors': factors,
        'waterfall': waterfall,
    })


# ── AI analysis (DeepSeek) ───────────────────────────────────────────────────

def _deepseek_chat(messages, timeout=90, model=None, max_tokens=1800):
    """Call DeepSeek chat completion API. Returns response text or raises.

    `model` overrides settings.DEEPSEEK_MODEL — used by the cockpit's group-level
    analysis to invoke the stronger DEEPSEEK_PRO_MODEL with a larger token budget.
    """
    import requests as req_lib
    resp = req_lib.post(
        f'{settings.DEEPSEEK_BASE_URL}/chat/completions',
        headers={
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json',
        },
        json={
            'model': model or settings.DEEPSEEK_MODEL,
            'messages': messages,
            'temperature': 0.3,
            'max_tokens': max_tokens,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()['choices'][0]['message']['content']


def _deepseek_stream(messages, model=None, max_tokens=1800, timeout=300):
    """Yield (kind, delta) from a streaming DeepSeek completion.

    kind ∈ {'reasoning', 'answer'}: reasoner models emit reasoning_content first
    (the chain-of-thought) then content (the final answer). Streaming both lets the
    UI show activity within seconds instead of waiting for the whole response.
    """
    import requests as req_lib
    resp = req_lib.post(
        f'{settings.DEEPSEEK_BASE_URL}/chat/completions',
        headers={
            'Authorization': f'Bearer {settings.DEEPSEEK_API_KEY}',
            'Content-Type': 'application/json',
        },
        json={
            'model': model or settings.DEEPSEEK_MODEL,
            'messages': messages,
            'temperature': 0.3,
            'max_tokens': max_tokens,
            'stream': True,
        },
        timeout=timeout,
        stream=True,
    )
    resp.raise_for_status()
    # Parse SSE lines as raw bytes → utf-8 (line boundaries never split multibyte chars).
    for raw in resp.iter_lines(decode_unicode=False):
        if not raw:
            continue
        line = raw.decode('utf-8', 'ignore')
        if not line.startswith('data:'):
            continue
        payload = line[5:].strip()
        if payload == '[DONE]':
            break
        try:
            delta = json.loads(payload)['choices'][0]['delta']
        except (ValueError, KeyError, IndexError):
            continue
        rc = delta.get('reasoning_content')
        if rc:
            yield ('reasoning', rc)
        c = delta.get('content')
        if c:
            yield ('answer', c)


def _sse_event(obj):
    """Encode one Server-Sent-Events frame."""
    return f'data: {json.dumps(obj, ensure_ascii=False)}\n\n'


def _fmt_wan(v):
    if v is None:
        return '无数据'
    try:
        v = float(v)
    except (TypeError, ValueError):
        return '无数据'
    sign = '-' if v < 0 else ''
    abs_v = abs(v)
    if abs_v >= 1e8:
        return f'{sign}{abs_v/1e8:.2f}亿元'
    if abs_v >= 1e4:
        return f'{sign}{abs_v/1e4:.2f}万元'
    return f'{sign}{abs_v:.2f}元'


_REPORT_AI_SYSTEM = '你是一位专业的企业财务分析师，擅长财务报表解读和经营决策分析，用中文回答。'


def _report_ai_prepare(request):
    """Shared validation + prompt build for the report AI endpoints.
    Returns (messages, None) on success or (None, err_response).

    Body: {year, month, bu? | bus?}"""
    if not settings.DEEPSEEK_API_KEY:
        return None, err('AI 分析未配置（缺少 DEEPSEEK_API_KEY）', 503)

    body = _parse_json(request)
    try:
        year = int(body.get('year'))
        month = int(body.get('month'))
        assert 2000 <= year <= 2100 and 1 <= month <= 12
    except Exception:
        return None, err('年份或月份无效')

    # Resolve BU scope from request, clamped to what this user may access.
    if request.pk_role == 'super_admin':
        accessible = list(BUSINESS_UNITS)
    else:
        accessible = [d for d in request.pk_depts if d in VALID_BUSINESS_UNITS]

    single_bu = (body.get('bu') or '').strip()
    req_bus = body.get('bus') or []
    if single_bu:
        if single_bu not in accessible:
            return None, err('无权访问该事业部', 403)
        bu_list = [single_bu]
        bu = single_bu
        bu_scope = ''
    elif req_bus:
        bu_list = [b for b in req_bus if b in accessible]
        if not bu_list:
            return None, err('无权访问所选事业部', 403)
        bu = '全集团' if len(bu_list) > 1 else bu_list[0]
        bu_scope = 'all' if len(bu_list) > 1 else ''
    else:
        bu_list = accessible
        bu = '全集团' if len(bu_list) != 1 else bu_list[0]
        bu_scope = 'all' if len(bu_list) > 1 else ''

    # Aggregate report data server-side (single source of truth).
    rows = _aggregate_report(_get_published_batches(bu_list, year, month), 1)
    if not rows:
        return None, err(f'{year}年{month}月该范围内暂无已发布数据，无法进行AI分析')

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    prev_rows = _aggregate_report(_get_published_batches(bu_list, prev_year, prev_month), 1)
    prev_kpis = {r['l1_name']: float(r['amount']) for r in prev_rows}

    # Build KPI summary with MoM change
    KPI_NAMES = ['主营业务收入', '主营业务成本', '运营毛利', '经营毛利', '经营净利']
    kpi_map = {r['l1_name']: r.get('amount') for r in rows}

    kpi_lines = []
    for name in KPI_NAMES:
        curr = kpi_map.get(name)
        prev = prev_kpis.get(name)
        line = f'  {name}：{_fmt_wan(curr)}'
        if curr is not None and prev is not None and prev != 0:
            delta_pct = (float(curr) - float(prev)) / abs(float(prev)) * 100
            trend = '↑' if delta_pct > 0 else '↓'
            line += f'（环比{trend}{abs(delta_pct):.1f}%，上月{_fmt_wan(prev)}）'
        elif curr is not None and prev is not None:
            line += f'（上月{_fmt_wan(prev)}，环比基数为零）'
        kpi_lines.append(line)

    # Other L1 items
    other_lines = []
    for r in rows:
        if r['l1_name'] not in KPI_NAMES and not r.get('is_calculated'):
            other_lines.append(f'  {r["l1_name"]}：{_fmt_wan(r.get("amount"))}')

    scope_note = ''
    if bu_scope == 'all':
        scope_note = '（以下为全集团合并口径，已排除集团总部内部往来，代表5个核心事业部合并情况）'

    prompt = f"""你是一位资深企业财务分析师，请对以下 {year}年{month}月 {bu} 的财务数据进行专业分析。{scope_note}

【关键财务指标】
{chr(10).join(kpi_lines)}

【其他科目明细】
{chr(10).join(other_lines) if other_lines else '  （无其他科目数据）'}

请从纯财务角度（业财融合分析将在后续版本中加入）进行以下分析：

1. **财务状况综合评价**（2-3句话，突出核心亮点或问题）
2. **关键指标分析**（重点分析盈利能力、成本管控，如有环比数据请分析变动趋势）
3. **风险提示**（负利润/异常波动/成本偏高等需警示的情况，如无风险可简要说明）
4. **决策建议**（2-3条具体可操作的财务管理建议）

要求：语言简明专业，适合集团领导决策参考，不超过600字。"""

    messages = [
        {'role': 'system', 'content': _REPORT_AI_SYSTEM},
        {'role': 'user', 'content': prompt},
    ]
    return messages, None


@cw_required()
def report_ai_analysis(request):
    """POST /report/ai-analysis — 单期财务分析（一次性返回）。"""
    if request.method != 'POST':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'report')
    if denied:
        return denied
    messages, e = _report_ai_prepare(request)
    if e:
        return e
    try:
        text = _deepseek_chat(messages)
        return ok({'analysis': text})
    except Exception as ex:
        logger.error(f'DeepSeek AI error: {ex}')
        return err(f'AI分析服务暂时不可用，请稍后重试（{str(ex)[:80]}）', 503)


@cw_required()
def report_ai_analysis_stream(request):
    """POST /report/ai-analysis/stream — 单期财务分析，SSE 流式逐字推送。"""
    if request.method != 'POST':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'report')
    if denied:
        return denied
    messages, e = _report_ai_prepare(request)
    if e:
        return e

    def gen():
        yield _sse_event({'type': 'meta'})
        try:
            for kind, delta in _deepseek_stream(messages):
                yield _sse_event({'type': kind, 'delta': delta})
            yield _sse_event({'type': 'done'})
        except Exception as ex:
            logger.error(f'DeepSeek AI stream error: {ex}')
            yield _sse_event({'type': 'error', 'error': f'AI分析服务暂时不可用（{str(ex)[:80]}）'})

    resp = StreamingHttpResponse(gen(), content_type='text/event-stream')
    resp['Cache-Control'] = 'no-cache'
    resp['X-Accel-Buffering'] = 'no'
    return resp


@cw_required()
def chart_ai_analysis(request):
    """POST /charts/ai-analysis
    Body: {chart_type: 'trend'|'waterfall', bu, year, month?, data: {...}}
    """
    if request.method != 'POST':
        return err('方法不允许', 405)
    denied = _page_denied(request, 'charts')
    if denied:
        return denied
    if not settings.DEEPSEEK_API_KEY:
        return err('AI 分析未配置（缺少 DEEPSEEK_API_KEY）', 503)

    body = _parse_json(request)
    chart_type = body.get('chart_type', 'trend')
    bu = body.get('bu', '未知事业部')
    year = body.get('year')
    data = body.get('data', {})

    if chart_type == 'trend':
        # Build trend narrative from 12-month data
        months_data = data.get('months', [])
        l1_cats = data.get('l1_categories', [])
        selected_ids = body.get('selected_l1_ids', [])
        sel_cats = [c for c in l1_cats if c['id'] in selected_ids] or l1_cats[:3]

        trend_lines = []
        for cat in sel_cats:
            vals = []
            for m in months_data:
                v = m.get('by_l1', {}).get(str(cat['id']))
                vals.append(f'{m["month"]}月:{_fmt_wan(v)}' if v is not None else f'{m["month"]}月:无')
            trend_lines.append(f'  {cat["name"]}：{", ".join(vals)}')

        prompt = f"""{year}年 {bu} 收入/利润走势数据如下：

{chr(10).join(trend_lines)}

请从财务角度分析：
1. 全年走势特征（旺季/淡季规律、增长趋势）
2. 月度异常波动（如某月大幅上升/下降的原因判断）
3. 结合该事业部全局情况的简要评价
4. 一条具体的改善建议

要求：简明专业，不超过300字。"""

    elif chart_type == 'waterfall':
        base = data.get('base_period', {})
        curr = data.get('current_period', {})
        factors = data.get('factors', [])
        factor_lines = [f'  {f["name"]}：变动{_fmt_wan(f["delta"])}（对利润影响）' for f in factors if f.get('delta')]

        prompt = f"""{bu} 利润因素分析（{base.get("year")}年{base.get("month")}月 vs {curr.get("year")}年{curr.get("month")}月）：

  基期经营净利：{_fmt_wan(base.get("total"))}
  当期经营净利：{_fmt_wan(curr.get("total"))}
  净变动：{_fmt_wan((curr.get("total") or 0) - (base.get("total") or 0))}

【驱动因素分解】
{chr(10).join(factor_lines) if factor_lines else "  暂无驱动因素数据"}

请从财务角度分析：
1. 利润变动的主要驱动因素评价
2. 正/负因素各自的关键点
3. 结合该事业部全局情况的评价
4. 一条针对性建议

要求：简明专业，不超过250字。"""
    else:
        return err('未知图表类型')

    try:
        text = _deepseek_chat([
            {'role': 'system', 'content': '你是一位专业的企业财务分析师，擅长图表数据解读，用中文简洁回答。'},
            {'role': 'user', 'content': prompt},
        ])
        return ok({'analysis': text})
    except Exception as e:
        logger.error(f'DeepSeek chart AI error: {e}')
        return err(f'AI分析暂时不可用（{str(e)[:80]}）', 503)
