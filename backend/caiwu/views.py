import io
import json
import logging
import datetime
import functools
import threading
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.db.models import Sum, Q
from django.conf import settings
from django.utils import timezone
import jwt

from caiwu.models import (
    CaiwuUser, L1Category, L2Category, L3Category,
    ImportBatch, FinancialEntry, CaiwuJobPermission,
    BUSINESS_UNITS, VALID_BUSINESS_UNITS, JOB_TITLES,
)

logger = logging.getLogger('caiwu')

BUILD_VERSION = '2026-05-24.2'

EXCEL_HEADERS = ['一级科目', '二级项目部', '三级科目明细', '金额(元)']
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
    {'key': 'report', 'label': '财务报表'},
    {'key': 'data',   'label': '数据加工'},
    {'key': 'charts', 'label': '图表分析'},
]
PAGE_KEYS = [p['key'] for p in PAGE_DEFS]


def _all_fields(value):
    return {k: value for k in FIELD_KEYS}


def default_job_config(job):
    """Sensible starting permissions for each job title; super_admin can override."""
    pages_all = {k: True for k in PAGE_KEYS}
    if job == 'finance_director':   # 财务总监 — full operational control
        return {'pages': pages_all, 'view': _all_fields(True),
                'can_upload': True, 'can_publish': True, 'can_delete': True}
    if job == 'finance_bp':         # 财务BP — upload + publish, no delete
        return {'pages': pages_all, 'view': _all_fields(True),
                'can_upload': True, 'can_publish': True, 'can_delete': False}
    if job == 'general_manager':    # 总经理 — read-only executive view
        return {'pages': {'report': True, 'data': False, 'charts': True},
                'view': _all_fields(True),
                'can_upload': False, 'can_publish': False, 'can_delete': False}
    # Unknown / no job title → read-only minimum.
    return {'pages': {'report': True, 'data': False, 'charts': True},
            'view': _all_fields(True),
            'can_upload': False, 'can_publish': False, 'can_delete': False}


_perm_cache = {}
_perm_cache_lock = threading.Lock()


def _invalidate_perm_cache(job=None):
    with _perm_cache_lock:
        if job:
            _perm_cache.pop(job, None)
        else:
            _perm_cache.clear()


def get_job_perms(job):
    """Effective config for a job title = defaults merged with stored overrides."""
    with _perm_cache_lock:
        if job in _perm_cache:
            return _perm_cache[job]
    base = default_job_config(job)
    try:
        rp = CaiwuJobPermission.objects.filter(job_title=job).first()
    except Exception:
        logger.warning('get_job_perms: DB unavailable for %s, using defaults', job)
        return base
    if not (rp and rp.config):
        result = base
    else:
        cfg = rp.config
        view = dict(base['view']);  view.update(cfg.get('view', {}))
        pages = dict(base['pages']); pages.update(cfg.get('pages', {}))
        result = {
            'pages': pages, 'view': view,
            'can_upload': bool(cfg.get('can_upload', base['can_upload'])),
            'can_publish': bool(cfg.get('can_publish', base['can_publish'])),
            'can_delete': bool(cfg.get('can_delete', base['can_delete'])),
        }
    with _perm_cache_lock:
        _perm_cache[job] = result
    return result


def full_perms():
    return {'pages': {k: True for k in PAGE_KEYS}, 'view': _all_fields(True),
            'can_upload': True, 'can_publish': True, 'can_delete': True}


def effective_perms(user):
    """Perms object sent to the client (super_admin gets full access)."""
    cfg = full_perms() if user.role == 'super_admin' else get_job_perms(user.job_title)
    return {**cfg, 'is_admin': user.role == 'super_admin',
            'fields': PERM_FIELD_DEFS, 'pages_meta': PAGE_DEFS}


def get_request_perms(request):
    """Effective perms for the authed request. None means full access (super_admin)."""
    if request.cw_role == 'super_admin':
        return None
    jt = getattr(request, 'cw_job', '') or ''
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
    def decorator(func):
        @functools.wraps(func)
        @csrf_exempt
        def wrapper(request, *args, **kwargs):
            token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
            if not token:
                return err('未认证', 401, 401)
            try:
                payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
                request.cw_uid = payload['uid']
                request.cw_role = payload['role']
                request.cw_job = payload.get('job', '')
                request.cw_depts = payload.get('departments', [])
            except jwt.ExpiredSignatureError:
                return err('Token已过期', 401, 401)
            except jwt.InvalidTokenError:
                return err('Token无效', 401, 401)
            # Re-validate user is still active (token may outlive a deactivation)
            try:
                u = CaiwuUser.objects.only('is_active').get(id=request.cw_uid)
                if not u.is_active:
                    return err('账号已停用', 401, 401)
            except CaiwuUser.DoesNotExist:
                return err('用户不存在', 401, 401)
            if roles and request.cw_role not in roles:
                return err('权限不足', 403, 403)
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def _bu_filter(qs, request):
    """Row visibility: super_admin sees all; everyone else sees assigned 事业部."""
    if request.cw_role == 'super_admin':
        return qs
    return qs.filter(business_unit__in=request.cw_depts)


def _can_access_bu(request, bu):
    if request.cw_role == 'super_admin':
        return True
    return bu in request.cw_depts


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
    if request.method != 'POST':
        return err('方法不允许', 405)
    body = _parse_json(request)
    phone = (body.get('phone') or '').strip()
    password = (body.get('password') or '').strip()
    name = (body.get('name') or '').strip()
    job_title = (body.get('job_title') or '').strip()
    departments = body.get('departments') or []

    if not phone or not password or not name:
        return err('手机号、密码、姓名均为必填')
    if not phone.isdigit() or len(phone) < 8:
        return err('手机号格式有误')
    if len(password) < 6:
        return err('密码至少6位')
    if not job_title or job_title not in JOB_TITLES:
        return err('请选择有效职务')
    if not isinstance(departments, list) or len(departments) == 0:
        return err('请至少选择一个事业部')

    existing = CaiwuUser.objects.filter(phone=phone).first()
    if existing:
        if existing.name != name:
            return err(f'该手机号已被"{existing.name}"注册，姓名不符')
        return err('该手机号已注册')
    if CaiwuUser.objects.filter(name=name).exists():
        return err('该姓名已被注册，如有疑问请联系管理员')

    is_first = not CaiwuUser.objects.exists()
    user = CaiwuUser(
        phone=phone,
        name=name,
        role='super_admin' if is_first else 'viewer',
        job_title=job_title,
        departments=departments if not is_first else [],
        is_approved=is_first,
    )
    user.set_password(password)
    user.save()

    if is_first:
        token = _make_token(user)
        return ok({'token': token, 'user': user.to_dict(),
                   'permissions': effective_perms(user), 'pending': False})
    return ok({'pending': True, 'msg': '注册成功！请等待管理员审批后登录'})


@csrf_exempt
def login(request):
    if request.method != 'POST':
        return err('方法不允许', 405)
    body = _parse_json(request)
    phone = (body.get('phone') or '').strip()
    password = (body.get('password') or '').strip()
    if not phone or not password:
        return err('手机号和密码不能为空')
    try:
        user = CaiwuUser.objects.get(phone=phone)
    except CaiwuUser.DoesNotExist:
        return err('手机号或密码错误')
    if not user.check_password(password):
        return err('手机号或密码错误')
    if not user.is_active:
        return err('账号已禁用，请联系管理员')
    if not user.is_approved:
        return ok({'pending': True, 'msg': '账号待审批，请联系管理员'})
    token = _make_token(user)
    return ok({'token': token, 'user': user.to_dict(), 'permissions': effective_perms(user)})


@csrf_exempt
def registration_status(request):
    """Public polling endpoint so a pending registrant can detect approval.

    Called with phone=__probe__ by Login.vue onMounted to detect whether the
    system has any users yet (so the UI can show a first-user hint banner).
    """
    if request.method != 'GET':
        return err('方法不允许', 405)
    phone = (request.GET.get('phone') or '').strip()
    if not phone:
        return err('缺少手机号')
    if phone == '__probe__':
        return ok({'has_users': CaiwuUser.objects.exists()})
    user = CaiwuUser.objects.filter(phone=phone).first()
    if not user:
        return ok({'status': 'none'})
    if not user.is_active:
        return ok({'status': 'rejected'})
    if user.is_approved:
        return ok({'status': 'approved'})
    return ok({'status': 'pending'})


@cw_required()
def me(request):
    if request.method != 'GET':
        return err('方法不允许', 405)
    try:
        user = CaiwuUser.objects.get(id=request.cw_uid)
    except CaiwuUser.DoesNotExist:
        return err('用户不存在', 404)
    token = _make_token(user)
    return ok({'token': token, 'user': user.to_dict(), 'permissions': effective_perms(user)})


# ── user management ──────────────────────────────────────────────────────────

@cw_required(roles=['super_admin'])
def users(request):
    if request.method == 'GET':
        qs = CaiwuUser.objects.all().order_by('-created_at')
        return ok([u.to_dict() for u in qs])
    if request.method == 'POST':
        body = _parse_json(request)
        phone = (body.get('phone') or '').strip()
        password = (body.get('password') or '').strip()
        name = (body.get('name') or '').strip()
        role = (body.get('role') or 'viewer').strip()
        job_title = (body.get('job_title') or '').strip()
        departments = body.get('departments', [])

        if not phone or not password or not name:
            return err('手机号、密码、姓名均为必填')
        if len(password) < 6:
            return err('密码至少6位')
        if role not in ('super_admin', 'viewer'):
            role = 'viewer'
        if role != 'super_admin':
            if job_title not in JOB_TITLES:
                return err('请选择有效职务')
            if not departments:
                return err('请至少分配一个事业部')
        if CaiwuUser.objects.filter(phone=phone).exists():
            return err('该手机号已注册')

        approver = CaiwuUser.objects.get(id=request.cw_uid)
        user = CaiwuUser(
            phone=phone, name=name, role=role,
            job_title=job_title if job_title in JOB_TITLES else '',
            departments=[] if role == 'super_admin' else departments,
            is_approved=True,
            approved_by=approver,
            approved_at=timezone.now(),
        )
        user.set_password(password)
        user.save()
        return ok(user.to_dict())
    return err('方法不允许', 405)


@cw_required(roles=['super_admin'])
def user_detail(request, uid):
    try:
        user = CaiwuUser.objects.get(id=uid)
    except CaiwuUser.DoesNotExist:
        return err('用户不存在', 404)

    if request.method == 'GET':
        return ok(user.to_dict())

    if request.method == 'PUT':
        body = _parse_json(request)
        name = (body.get('name') or '').strip()
        if not name:
            return err('姓名不能为空')
        job_title = (body.get('job_title') or user.job_title).strip()
        departments = body.get('departments', user.departments)

        # super_admin keeps full scope; everyone else is scoped by 事业部.
        if user.role != 'super_admin' and not departments:
            return err('请至少分配一个事业部')

        user.name = name
        user.job_title = job_title if job_title in JOB_TITLES else user.job_title
        if user.role != 'super_admin':
            user.departments = departments
        user.is_active = bool(body.get('is_active', user.is_active))

        if 'password' in body and body['password']:
            pw = str(body['password']).strip()
            if len(pw) < 6:
                return err('密码至少6位')
            user.set_password(pw)

        user.save()
        return ok(user.to_dict())

    if request.method == 'DELETE':
        if user.role == 'super_admin':
            return err('不能删除超级管理员账号', 403)
        user.delete()
        return ok({'deleted': uid})

    return err('方法不允许', 405)


@cw_required(roles=['super_admin'])
def user_approve(request, uid):
    if request.method != 'POST':
        return err('方法不允许', 405)
    try:
        user = CaiwuUser.objects.get(id=uid)
    except CaiwuUser.DoesNotExist:
        return err('用户不存在', 404)
    body = _parse_json(request)
    job_title = (body.get('job_title') or user.job_title or '').strip()
    if job_title not in JOB_TITLES:
        return err('请选择有效职务')
    departments = body.get('departments', [])
    if not departments:
        return err('请至少分配一个事业部')

    approver = CaiwuUser.objects.get(id=request.cw_uid)
    user.role = 'viewer'
    user.job_title = job_title
    user.departments = departments
    user.is_approved = True
    user.approved_by = approver
    user.approved_at = timezone.now()
    user.save()
    return ok(user.to_dict())


@cw_required(roles=['super_admin'])
def user_reject(request, uid):
    if request.method != 'POST':
        return err('方法不允许', 405)
    try:
        user = CaiwuUser.objects.get(id=uid)
    except CaiwuUser.DoesNotExist:
        return err('用户不存在', 404)
    user.is_active = False
    user.save()
    return ok({'id': uid, 'status': 'rejected'})


# ── job-title permission config (super_admin) ────────────────────────────────

@cw_required(roles=['super_admin'])
def permissions(request):
    """GET: full permission matrix for all job titles + field/page metadata."""
    if request.method != 'GET':
        return err('方法不允许', 405)
    jobs = [
        {'job_title': key, 'label': label, 'config': get_job_perms(key)}
        for key, label in JOB_TITLES.items()
    ]
    return ok({
        'fields': PERM_FIELD_DEFS,
        'pages': PAGE_DEFS,
        'jobs': jobs,
    })


@cw_required(roles=['super_admin'])
def permission_detail(request, job):
    """PUT: update one job title's permission config."""
    if request.method != 'PUT':
        return err('方法不允许', 405)
    if job not in JOB_TITLES:
        return err('职务无效', 404)
    body = _parse_json(request)
    cfg = body.get('config') or {}
    clean = {
        'pages': {k: bool(cfg.get('pages', {}).get(k, True)) for k in PAGE_KEYS},
        'view': {k: bool(cfg.get('view', {}).get(k, True)) for k in FIELD_KEYS},
        'can_upload': bool(cfg.get('can_upload', False)),
        'can_publish': bool(cfg.get('can_publish', False)),
        'can_delete': bool(cfg.get('can_delete', False)),
    }
    obj, _ = CaiwuJobPermission.objects.get_or_create(job_title=job)
    obj.config = clean
    obj.save()
    _invalidate_perm_cache(job)
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

    # Example row
    ws.cell(row=2, column=1, value='主营业务收入')
    ws.cell(row=2, column=2, value='甲项目部（可选）')
    ws.cell(row=2, column=3, value='工程款（可选）')
    ws.cell(row=2, column=4, value=1000000.00)

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 24
    ws.column_dimensions['D'].width = 16

    # Instruction sheet
    ws2 = wb.create_sheet('填写说明')
    instructions = [
        ['列名', '说明', '是否必填'],
        ['一级科目', '必须与系统中已配置的一级科目名称完全一致', '必填'],
        ['二级项目部', '该事业部下的项目部名称，系统会自动创建不存在的项目部', '选填'],
        ['三级科目明细', '成本费用科目明细，系统会自动创建不存在的明细', '选填'],
        ['金额(元)', '数值，可为负数（如成本类）', '必填'],
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

    return _build_excel_response(wb, '财务数据导入模板.xlsx')


# ── Kingdee 部门明细表 format detection ──────────────────────────────────────

_KD_ACCT_KW   = ['科目名称', '科目全称', '一级科目名称', '一级科目']
_KD_DEPT_KW   = ['部门']
_KD_DEBIT_KW  = ['本期借方', '借方发生额', '本期发生(借', '发生额(借', '本月发生额(借']
_KD_CREDIT_KW = ['本期贷方', '贷方发生额', '本期发生(贷', '发生额(贷', '本月发生额(贷']
_KD_AMT_KW    = ['本期金额', '本月发生额', '发生额合计', '本年金额']
_KD_L3_KW     = ['明细科目', '三级科目', '科目明细', '子目', '小科目']
_KD_SKIP_KW   = ['合计', '小计', '总计', '期末', '期初', '余额', '科目代码', '科目编码', '编码']


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

        # Compute amount (store as positive; abs(net) covers both directions)
        if 'debit' in cm and 'credit' in cm:
            amount = abs(cn(cm['credit']) - cn(cm['debit']))
        else:
            amount = abs(cn(cm['amount']))

        if amount == 0:
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

        parsed.append({
            'l1': l1, 'l2': l2, 'l3': l3, 'amount': amount,
            'l1_name': matched_name, 'l2_name': dept, 'l3_name': l3_name,
        })

    return parsed, errors


def _parse_template_rows(ws, bu, l1_map, l2_map, l3_map):
    """Parse the KXT 4-column custom template format. Returns (parsed_rows, errors)."""
    errors = []
    parsed = []

    for ri in range(2, ws.max_row + 1):
        l1_name = str(ws.cell(row=ri, column=1).value or '').strip()
        l2_name = str(ws.cell(row=ri, column=2).value or '').strip()
        l3_name = str(ws.cell(row=ri, column=3).value or '').strip()
        amt_raw = ws.cell(row=ri, column=4).value

        if not l1_name and not l2_name and not l3_name and amt_raw is None:
            continue

        if not l1_name:
            errors.append(f'第{ri}行：一级科目不能为空')
            continue
        if l1_name not in l1_map:
            errors.append(f'第{ri}行：一级科目"{l1_name}"不存在，请先在设置中添加')
            continue
        if l1_map[l1_name].is_calculated:
            continue  # skip calculated rows silently

        try:
            amount = Decimal(str(amt_raw))
        except (InvalidOperation, TypeError):
            errors.append(f'第{ri}行：金额"{amt_raw}"格式错误')
            continue

        l1 = l1_map[l1_name]
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
                l3_obj = L3Category(
                    business_unit=bu, l1_category=l1, name=l3_name, sort_order=len(l3_map),
                )
                l3_obj.save()
                l3_map[key] = l3_obj
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

    try:
        import openpyxl
        wb = openpyxl.load_workbook(f, data_only=True)
        ws = wb.active
    except Exception:
        return err('文件格式错误，请使用Excel(.xlsx)格式')

    l1_map = {c.name: c for c in L1Category.objects.all()}
    if not l1_map:
        return err('系统尚未配置一级科目，请先在「设置」中添加一级科目')

    l2_map = {c.name: c for c in L2Category.objects.filter(business_unit=bu)}
    l3_map = {(c.l1_category_id, c.name): c for c in L3Category.objects.filter(business_unit=bu)}

    # Auto-detect format: try KXT template first, then Kingdee
    row1_headers = [str(ws.cell(row=1, column=c).value or '').strip() for c in range(1, 5)]
    if row1_headers == EXCEL_HEADERS:
        parsed_rows, errors = _parse_template_rows(ws, bu, l1_map, l2_map, l3_map)
        fmt = 'template'
    else:
        data_start, cm = _detect_kingdee_format(ws)
        if data_start is None:
            return err(
                '无法识别文件格式。支持两种格式：\n'
                '① KXT模板（四列：一级科目/二级项目部/三级科目明细/金额）\n'
                '② 金蝶部门明细表（含"科目名称"+"部门"+"本期借方/贷方"列）'
            )
        parsed_rows, errors = _parse_kingdee_rows(ws, data_start, cm, bu, l1_map, l2_map, l3_map)
        fmt = 'kingdee'

    # Non-fatal warnings: show up to 5, but don't block import
    warnings = errors[:10] if errors else []

    if not parsed_rows:
        hint = '；'.join(errors[:3]) if errors else '文件中没有有效数据行'
        return err(hint)

    # Compute P&L reconciliation before saving
    pl_check = _compute_pl_check(parsed_rows)

    # Create draft batch + entries atomically so a bulk_create failure
    # doesn't leave an empty orphaned batch record.
    uploader = CaiwuUser.objects.get(id=request.cw_uid)
    with transaction.atomic(using='caiwu'):
        batch = ImportBatch.objects.create(
            business_unit=bu, year=year, month=month,
            status=ImportBatch.STATUS_DRAFT,
            uploaded_by=uploader,
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
    with transaction.atomic(using='caiwu'):
        # Re-fetch with lock to guard against concurrent publish
        try:
            batch = ImportBatch.objects.select_for_update().get(id=bid)
        except ImportBatch.DoesNotExist:
            return err('批次不存在', 404)
        if batch.status == ImportBatch.STATUS_PUBLISHED:
            return err('该批次已发布')

        # Retire any previously published batch for same BU+month
        old_published = ImportBatch.objects.select_for_update().filter(
            business_unit=batch.business_unit,
            year=batch.year,
            month=batch.month,
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


# ── report ───────────────────────────────────────────────────────────────────

def _get_published_batches(bu_list, year, month):
    """Return published ImportBatch objects for given BUs and period."""
    return ImportBatch.objects.filter(
        business_unit__in=bu_list,
        year=year, month=month,
        status=ImportBatch.STATUS_PUBLISHED,
    )


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
    if request.cw_role == 'super_admin':
        accessible = BUSINESS_UNITS
    else:
        accessible = [d for d in request.cw_depts if d in VALID_BUSINESS_UNITS]

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
        r['amount'] for r in rows if not r.get('is_calculated')
    )
    total_label = '经营净利' if profit_row else '合计金额'
    return ok({
        'rows': rows, 'total': total, 'total_label': total_label,
        'level': level, 'year': year, 'month': month, 'bu': bu_param or None,
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

    if request.cw_role == 'super_admin':
        accessible = BUSINESS_UNITS
    else:
        accessible = [d for d in request.cw_depts if d in VALID_BUSINESS_UNITS]

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

    l1_cats = list(L1Category.objects.all())

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

    l1_cats = list(L1Category.objects.all())

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

    # Headline profit = 经营净利 if configured, else sum of raw entries
    base_total = base_name_map.get('经营净利', sum(
        v for l1 in l1_cats if not l1.is_calculated
        for v in [base_id_map.get(l1.id, 0)]
    ))
    curr_total = curr_name_map.get('经营净利', sum(
        v for l1 in l1_cats if not l1.is_calculated
        for v in [curr_id_map.get(l1.id, 0)]
    ))

    # Factor analysis using profit-driver raw L1 categories (not calculated rows).
    # delta is sign-adjusted so positive always means "profit improved".
    drivers = [l1 for l1 in l1_cats if l1.is_profit_driver and not l1.is_calculated]

    factors = []
    for l1 in drivers:
        base_v = base_id_map.get(l1.id, 0)
        curr_v = curr_id_map.get(l1.id, 0)
        raw_delta = curr_v - base_v
        # sign=-1 means cost: cost increase hurts profit → negate
        profit_delta = raw_delta * l1.sign
        factors.append({
            'l1_id': l1.id,
            'name': l1.name,
            'base': base_v,
            'current': curr_v,
            'delta': profit_delta,
        })

    # Waterfall items: start → factors → end
    waterfall = [
        {'name': f'{cmp_year}年{cmp_month}月', 'value': base_total, 'type': 'base'},
    ]
    for f in factors:
        waterfall.append({
            'name': f['name'],
            'value': f['delta'],
            'type': 'increase' if f['delta'] >= 0 else 'decrease',
        })
    waterfall.append({'name': f'{year}年{month}月', 'value': curr_total, 'type': 'total'})

    return ok({
        'bu': bu,
        'base_period': {'year': cmp_year, 'month': cmp_month, 'total': base_total},
        'current_period': {'year': year, 'month': month, 'total': curr_total},
        'factors': factors,
        'waterfall': waterfall,
    })
