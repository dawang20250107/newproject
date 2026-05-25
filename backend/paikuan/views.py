import io
import json
import logging
import datetime
import functools
import re
import threading
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import F, Q, Sum, Count, Case, When, ExpressionWrapper
from django.db.models import DecimalField as DjDecimalField
from django.conf import settings
from django.utils import timezone
import jwt

from paikuan.models import PaikuanUser, Payment, JobPermission

logger = logging.getLogger('paikuan')

DEPARTMENTS = [
    '集团总部', '劳务事业部', '运输事业部', '自营事业部',
    '阔展事业部', '多式联运事业部', '供应链事业部',
]
VALID_DEPARTMENTS = set(DEPARTMENTS)

# Job titles double as the permission "roles" configured by super_admin.
JOB_TITLES = {
    'finance_director': '财务总监',
    'finance_bp': '财务BP',
    'chief_cashier': '总出纳',
    'cashier': '出纳',
}

# ── permission model ────────────────────────────────────────────────────────────
# Payment fields that can be individually permission-controlled. Each logical
# field maps to one or more columns in the serialized payment dict.
PAYMENT_FIELD_DEFS = [
    {'key': 'department',      'label': '部门',         'cols': ['department']},
    {'key': 'approval_number', 'label': '审批单号',      'cols': ['approval_number']},
    {'key': 'project_desc',    'label': '付款事项',      'cols': ['project_desc']},
    {'key': 'payee',           'label': '收款方',        'cols': ['payee']},
    {'key': 'total_amount',    'label': '计划总金额',    'cols': ['total_amount']},
    {'key': 'planned_date',    'label': '计划付款日期',  'cols': ['planned_date']},
    {'key': 'pay1',            'label': '第1次付款',     'cols': ['pay1_date', 'pay1_amount']},
    {'key': 'pay2',            'label': '第2次付款',     'cols': ['pay2_date', 'pay2_amount']},
    {'key': 'pay3',            'label': '第3次付款',     'cols': ['pay3_date', 'pay3_amount']},
    {'key': 'notes',           'label': '备注',          'cols': ['notes']},
]
FIELD_KEYS = [f['key'] for f in PAYMENT_FIELD_DEFS]
PAGE_KEYS = [
    'dashboard', 'payments', 'stats',
    'ar_projects', 'ar_records', 'ar_analytics', 'ar_cashflow', 'ar_budget',
]

# Ordered columns for Excel template / import / export.
# (perm_field_key, excel_header, db_column)
EXCEL_COLUMN_MAP = [
    ('department',      '部门',               'department'),
    ('approval_number', '审批单号',            'approval_number'),
    ('project_desc',    '付款事项',            'project_desc'),
    ('payee',           '收款方',              'payee'),
    ('total_amount',    '计划总金额(元)',       'total_amount'),
    ('planned_date',    '计划付款日期',         'planned_date'),
    ('pay1',            '第1次付款日期',        'pay1_date'),
    ('pay1',            '第1次付款金额(元)',    'pay1_amount'),
    ('pay2',            '第2次付款日期',        'pay2_date'),
    ('pay2',            '第2次付款金额(元)',    'pay2_amount'),
    ('pay3',            '第3次付款日期',        'pay3_date'),
    ('pay3',            '第3次付款金额(元)',    'pay3_amount'),
    ('notes',           '备注',                'notes'),
]
_EXCEL_HEADER_TO_COL = {h: c for _, h, c in EXCEL_COLUMN_MAP}
_EXCEL_DATE_COLS = {'planned_date', 'pay1_date', 'pay2_date', 'pay3_date'}

# Example row in the template carries this marker in 部门 so import skips it
# even when the user forgets to delete it.
EXAMPLE_ROW_MARKER = '示例-导入前请删除此行'


def _normalize_date(s):
    """Best-effort normalize a user-typed date string to ISO YYYY-MM-DD."""
    s = (str(s) or '').strip()
    if not s:
        return None
    s = s.replace('/', '-').replace('.', '-').replace('年', '-').replace('月', '-').replace('日', '')
    parts = [p for p in s.split('-') if p != '']
    try:
        if len(parts) >= 3:
            return f'{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}'
    except ValueError:
        pass
    return s  # leave as-is; downstream save will reject if truly invalid


def _all_fields(value):
    return {k: value for k in FIELD_KEYS}


def default_job_config(job):
    """Sensible starting permissions for each job title; super_admin can override."""
    pages_all = {k: True for k in PAGE_KEYS}
    ar_pages_all = {k: True for k in ('ar_projects', 'ar_records', 'ar_analytics', 'ar_cashflow', 'ar_budget')}
    ar_pages_cashier = {k: (k in ('ar_records', 'ar_cashflow', 'ar_budget')) for k in ar_pages_all}
    if job == 'finance_director':
        return {'pages': pages_all, 'view': _all_fields(True),
                'edit': _all_fields(True), 'can_create': True, 'can_delete': True}
    if job == 'finance_bp':
        return {'pages': pages_all, 'view': _all_fields(True),
                'edit': _all_fields(True), 'can_create': True, 'can_delete': False}
    if job == 'chief_cashier':
        edit = {k: (k in ('pay1', 'pay2', 'pay3')) for k in FIELD_KEYS}
        pages = {**pages_all, **ar_pages_all}
        return {'pages': pages, 'view': _all_fields(True),
                'edit': edit, 'can_create': True, 'can_delete': False}
    if job == 'cashier':
        edit = {k: (k in ('pay1', 'pay2', 'pay3')) for k in FIELD_KEYS}
        base_pages = {'dashboard': True, 'payments': True, 'stats': False}
        return {'pages': {**base_pages, **ar_pages_cashier},
                'view': _all_fields(True), 'edit': edit,
                'can_create': False, 'can_delete': False}
    # Unknown / no job title → read-only minimum.
    return {'pages': pages_all, 'view': _all_fields(True),
            'edit': _all_fields(False), 'can_create': False, 'can_delete': False}


_perm_cache: dict = {}
_perm_cache_lock = threading.Lock()


def _invalidate_perm_cache(job=None):
    with _perm_cache_lock:
        if job:
            _perm_cache.pop(job, None)
        else:
            _perm_cache.clear()


def get_job_perms(job):
    """Effective config for a job title = defaults merged with stored overrides.
    Results are cached per-process to avoid repeated DB lookups."""
    with _perm_cache_lock:
        if job in _perm_cache:
            return _perm_cache[job]
    base = default_job_config(job)
    try:
        rp = JobPermission.objects.filter(job_title=job).first()
    except Exception:
        # paikuan_job_permissions table may not exist yet (migration pending).
        logger.warning('get_job_perms: DB unavailable for %s, using defaults', job)
        return base
    if not (rp and rp.config):
        result = base
    else:
        cfg = rp.config
        view = dict(base['view']);  view.update(cfg.get('view', {}))
        edit = dict(base['edit']);  edit.update(cfg.get('edit', {}))
        pages = dict(base['pages']); pages.update(cfg.get('pages', {}))
        result = {
            'pages': pages, 'view': view, 'edit': edit,
            'can_create': bool(cfg.get('can_create', base['can_create'])),
            'can_delete': bool(cfg.get('can_delete', base['can_delete'])),
        }
    with _perm_cache_lock:
        _perm_cache[job] = result
    return result


def full_perms():
    return {'pages': {k: True for k in PAGE_KEYS}, 'view': _all_fields(True),
            'edit': _all_fields(True), 'can_create': True, 'can_delete': True}


def effective_perms(user):
    """Perms object sent to the client (super_admin gets full access)."""
    cfg = full_perms() if user.role == 'super_admin' else get_job_perms(user.job_title)
    return {**cfg, 'is_admin': user.role == 'super_admin', 'fields': PAYMENT_FIELD_DEFS}


def get_request_perms(request):
    """Effective perms for the authed request. None means full access (super_admin)."""
    if request.pk_role == 'super_admin':
        return None
    jt = getattr(request, 'pk_job', '') or ''
    if not jt:
        u = PaikuanUser.objects.filter(id=request.pk_uid).only('job_title').first()
        jt = u.job_title if u else ''
    return get_job_perms(jt)


def apply_view_mask(d, perms):
    """Null out payment-dict fields the role cannot view."""
    if perms is None:
        return d
    view = perms['view']
    hide_cols = set()
    for f in PAYMENT_FIELD_DEFS:
        if not view.get(f['key'], True):
            hide_cols.update(f['cols'])
    for c in hide_cols:
        if c in d:
            d[c] = None
    pay_hidden = any(not view.get(k, True) for k in ('pay1', 'pay2', 'pay3'))
    if pay_hidden:
        d['total_paid'] = None
    if pay_hidden or not view.get('total_amount', True):
        d['remaining'] = None
    return d


# ── helpers ───────────────────────────────────────────────────────────────────

def _no_store(resp):
    # API data is per-user and mutates frequently (e.g. user deletion); never let
    # a browser or proxy serve a stale copy that would resurrect deleted records.
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp['Pragma'] = 'no-cache'
    return resp


def ok(data=None):
    return _no_store(JsonResponse({'code': 0, 'data': data}))


def err(msg, status=400, code=-1):
    return _no_store(JsonResponse({'code': code, 'error': msg}, status=status))


def parse_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return {}


def make_token(user):
    payload = {
        'uid': user.id,
        'role': user.role,
        'job': user.job_title,
        'departments': user.departments,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        'iat': datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm='HS256')


def pk_required(roles=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kwargs):
            token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
            if not token:
                return err('未认证', 401, 401)
            try:
                payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
                uid = payload['uid']
            except jwt.ExpiredSignatureError:
                return err('Token已过期', 401, 401)
            except (jwt.InvalidTokenError, KeyError):
                return err('Token无效', 401, 401)
            user = PaikuanUser.objects.filter(id=uid).first()
            if not user:
                return err('用户不存在或登录已失效', 401, 401)
            if not user.is_active:
                return err('账号已停用，请重新登录', 401, 401)
            if not user.is_approved:
                return err('账号待审批，请联系管理员', 403, -2)
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


def _payments_page_denied(request, perms=None):
    perms = get_request_perms(request) if perms is None else perms
    if perms is not None and not perms['pages'].get('payments', True):
        return err('无访问权限', 403, 403)
    return None


def dept_filter(qs, request):
    """Row visibility: super_admin sees all; everyone else sees assigned departments."""
    if request.pk_role == 'super_admin':
        return qs
    return qs.filter(department__in=request.pk_depts)


def can_write_dept(request, dept):
    if request.pk_role == 'super_admin':
        return True
    return dept in request.pk_depts


_DEC = DjDecimalField(max_digits=15, decimal_places=2)


def _paid_expr():
    """SQL expression for total paid = pay1+pay2+pay3."""
    return ExpressionWrapper(
        F('pay1_amount') + F('pay2_amount') + F('pay3_amount'), output_field=_DEC
    )


def _remaining_expr():
    """SQL expression for remaining = total_amount - paid."""
    return ExpressionWrapper(
        F('total_amount') - F('pay1_amount') - F('pay2_amount') - F('pay3_amount'),
        output_field=_DEC,
    )


# ── version / deploy check ──────────────────────────────────────────────────────
# Bump BUILD_VERSION whenever backend behaviour changes so a deploy can be verified
# by opening /api/pk/version in a browser (no auth required).
BUILD_VERSION = '2026-05-23.6'


@csrf_exempt
def version(request):
    return ok({
        'version': BUILD_VERSION,
        'features': {
            'hard_delete_user': True,      # DELETE /users/<id> permanently removes the row
            'stats_dept_filter': True,     # GET /stats?depts=A,B filters by department
            'no_store_headers': True,      # API responses are never cached
        },
    })


# ── auth ──────────────────────────────────────────────────────────────────────

@csrf_exempt
def register(request):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    data = parse_body(request)
    phone = (data.get('phone') or '').strip()
    password = (data.get('password') or '').strip()
    name = (data.get('name') or '').strip()
    job_title = (data.get('job_title') or '').strip()
    depts = data.get('departments') or []

    if not phone or not password or not name:
        return err('手机号、密码和姓名均必填')
    if not phone.isdigit() or len(phone) < 8:
        return err('手机号格式有误')
    if len(password) < 6:
        return err('密码至少6位')
    if not job_title or job_title not in JOB_TITLES:
        return err('请选择有效职务')
    if not isinstance(depts, list) or len(depts) == 0:
        return err('请至少选择一个部门')

    # Phone uniqueness
    existing = PaikuanUser.objects.filter(phone=phone).first()
    if existing:
        if existing.name != name:
            return err(f'该手机号已被"{existing.name}"注册，姓名不符')
        return err('该手机号已注册')
    # Name uniqueness — each person should have exactly one account
    if PaikuanUser.objects.filter(name=name).exists():
        return err('该姓名已被注册，如有疑问请联系管理员')

    is_first = not PaikuanUser.objects.exists()
    role = 'super_admin' if is_first else 'viewer'

    user = PaikuanUser(
        phone=phone, name=name, role=role,
        job_title=job_title,
        departments=depts if role != 'super_admin' else [],
        is_approved=is_first,
    )
    user.set_password(password)
    user.save()

    if is_first:
        return ok({'token': make_token(user), 'user': user.to_dict(),
                   'permissions': effective_perms(user), 'pending': False})
    return ok({'pending': True, 'message': '注册成功！请等待管理员审批后登录'})


@csrf_exempt
def login(request):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    data = parse_body(request)
    phone = (data.get('phone') or '').strip()
    password = (data.get('password') or '').strip()
    if not phone or not password:
        return err('手机号和密码均必填')
    try:
        user = PaikuanUser.objects.get(phone=phone)
    except PaikuanUser.DoesNotExist:
        return err('手机号或密码错误', 401, 401)
    if not user.is_active:
        return err('账号已停用，请联系管理员', 401, 401)
    if not user.check_password(password):
        return err('手机号或密码错误', 401, 401)
    if not user.is_approved:
        return err('账号待审批，请联系管理员', 403, -2)
    return ok({'token': make_token(user), 'user': user.to_dict(),
               'permissions': effective_perms(user)})


@csrf_exempt
def registration_status(request):
    """Public polling endpoint so a pending registrant can detect approval."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    phone = (request.GET.get('phone') or '').strip()
    if not phone:
        return err('缺少手机号')
    user = PaikuanUser.objects.filter(phone=phone).first()
    if not user:
        return ok({'status': 'none'})
    if not user.is_active:
        return ok({'status': 'rejected'})
    if user.is_approved:
        return ok({'status': 'approved'})
    return ok({'status': 'pending'})


@pk_required()
def me(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    try:
        user = PaikuanUser.objects.get(id=request.pk_uid)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)
    return ok({'user': user.to_dict(), 'permissions': effective_perms(user)})


# ── payments ──────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def payments(request):
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    if request.method == 'GET':
        return _list_payments(request)
    if request.method == 'POST':
        return _create_payment(request)
    return err('Method not allowed', 405)


def _list_payments(request):
    qs = Payment.objects.select_related('created_by').all()
    qs = dept_filter(qs, request)

    dept = request.GET.get('dept', '').strip()
    status_q = request.GET.get('status', '').strip()
    start = request.GET.get('start_date', '').strip()
    end = request.GET.get('end_date', '').strip()
    q = request.GET.get('q', '').strip()

    if dept:
        qs = qs.filter(department=dept)
    if start:
        qs = qs.filter(planned_date__gte=start)
    if end:
        qs = qs.filter(planned_date__lte=end)
    if q:
        qs = qs.filter(
            Q(project_desc__icontains=q) | Q(payee__icontains=q) |
            Q(approval_number__icontains=q) | Q(department__icontains=q)
        )

    try:
        page = max(1, int(request.GET.get('page', 1)))
        size = min(200, max(1, int(request.GET.get('size', 50))))
    except ValueError:
        page, size = 1, 50

    # Status filter via SQL annotation — avoids fetching all rows into Python.
    if status_q:
        qs = qs.annotate(paid=_paid_expr())
        if status_q == 'pending':
            qs = qs.filter(paid=Decimal('0'))
        elif status_q == 'settled':
            qs = qs.filter(paid__gte=F('total_amount'))
        elif status_q == 'partial':
            qs = qs.filter(paid__gt=Decimal('0'), paid__lt=F('total_amount'))

    total = qs.count()
    perms = get_request_perms(request)
    items = [apply_view_mask(p.to_dict(), perms) for p in qs[(page - 1) * size: page * size]]
    return ok({'items': items, 'total': total, 'page': page, 'size': size})


def _parse_payment_fields(data, payment=None):
    fields = {}

    def get(key, default=None):
        return data.get(key, getattr(payment, key, default) if payment else default)

    fields['department'] = (get('department') or '').strip()
    fields['approval_number'] = (get('approval_number') or '').strip()
    fields['project_desc'] = (get('project_desc') or '').strip()
    fields['payee'] = (get('payee') or '').strip()
    fields['notes'] = (get('notes') or '').strip()

    def _num(key):
        raw = get(key, 0)
        s = str(raw if raw not in (None, '') else 0)
        # Tolerate thousands separators / full-width commas / currency symbol.
        s = s.replace(',', '').replace('，', '').replace('¥', '').replace('￥', '').strip()
        return Decimal(s or '0')

    try:
        fields['total_amount'] = _num('total_amount')
        fields['pay1_amount'] = _num('pay1_amount')
        fields['pay2_amount'] = _num('pay2_amount')
        fields['pay3_amount'] = _num('pay3_amount')
    except (InvalidOperation, TypeError) as e:
        return None, f'金额格式有误: {e}'

    _AMT_LABELS = {
        'total_amount': '计划总金额',
        'pay1_amount': '第1次付款金额',
        'pay2_amount': '第2次付款金额',
        'pay3_amount': '第3次付款金额',
    }
    # Reject negative amounts
    for amt_key, label in _AMT_LABELS.items():
        if fields[amt_key] < Decimal('0'):
            return None, f'{label}不能为负数'
    if fields['total_amount'] <= Decimal('0'):
        return None, '计划总金额必须大于0'

    # Hard-reject overpayment: installment sum must not exceed total
    total_paid = fields['pay1_amount'] + fields['pay2_amount'] + fields['pay3_amount']
    if total_paid > fields['total_amount']:
        _ta = fields['total_amount']
        return None, (
            f'实付总额（{total_paid}元）超出计划总金额（{_ta}元），'
            '请核实金额后再提交'
        )

    for key in ('planned_date', 'pay1_date', 'pay2_date', 'pay3_date'):
        val = data.get(key) if key in data else getattr(payment, key, None)
        fields[key] = val or None

    # D1: Validate that date strings represent actual calendar dates.
    # Rejects impossible dates like 2026-02-30 or 2026-13-01 before they reach the ORM.
    _DATE_LABELS = {
        'planned_date': '计划付款', 'pay1_date': '第1次付款',
        'pay2_date': '第2次付款', 'pay3_date': '第3次付款',
    }
    for key, label in _DATE_LABELS.items():
        if fields[key]:
            try:
                datetime.date.fromisoformat(str(fields[key]))
            except ValueError:
                return None, f'{label}日期无效（{fields[key]}），请使用 YYYY-MM-DD 格式'

    # Paired installment validation: date↔amount must both be present or both absent
    for n, date_key, amt_key in (
        (1, 'pay1_date', 'pay1_amount'),
        (2, 'pay2_date', 'pay2_amount'),
        (3, 'pay3_date', 'pay3_amount'),
    ):
        has_date = bool(fields[date_key])
        has_amt = fields[amt_key] > Decimal('0')
        if has_amt and not has_date:
            return None, f'第{n}次付款填写了金额，但缺少日期'
        if has_date and not has_amt:
            return None, f'第{n}次付款填写了日期，但金额为0'

    if not fields['department']:
        return None, '部门必填'
    if fields['department'] not in VALID_DEPARTMENTS:
        return None, f'部门"{fields["department"]}"无效，请使用系统预设部门'
    if not fields['project_desc']:
        return None, '付款事项描述必填'
    if not fields['payee']:
        return None, '收款方必填'
    # Payee must be text (letters/Chinese/digits/common punctuation only — no HTML/control chars)
    if fields['payee'] and re.search(r'[<>{}\[\]|\\^~`@#$%&*=+]', fields['payee']):
        return None, '收款方仅允许输入文字内容，不能含特殊符号'
    if not fields['planned_date']:
        return None, '计划付款日期必填'
    # Approval number: must be exactly 21 digits when provided
    if fields['approval_number'] and not re.fullmatch(r'\d{21}', fields['approval_number']):
        return None, '审批单号须为21位数字（如不填写可留空）'

    return fields, None


def _create_payment(request):
    perms = get_request_perms(request)
    if perms is not None and not perms['can_create']:
        return err('无新增权限', 403, 403)
    data = parse_body(request)
    fields, error = _parse_payment_fields(data)
    if error:
        return err(error)
    if not can_write_dept(request, fields['department']):
        return err('无权操作该部门', 403, 403)
    p = Payment(created_by_id=request.pk_uid, **fields)
    p.save()
    return ok(p.to_dict())


def _editable_payment_payload(data, perms):
    """Drop non-editable payment fields before merge+validation on update."""
    if perms is None:
        return data
    editable_cols = set()
    for f in PAYMENT_FIELD_DEFS:
        if perms['edit'].get(f['key'], False):
            editable_cols.update(f['cols'])
    return {k: v for k, v in data.items() if k in editable_cols}


@csrf_exempt
@pk_required()
def payment_detail(request, pk):
    try:
        p = Payment.objects.select_related('created_by').get(id=pk)
    except Payment.DoesNotExist:
        return err('记录不存在', 404)

    if not dept_filter(Payment.objects.filter(id=pk), request).exists():
        return err('无权访问', 403, 403)

    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied

    if request.method == 'GET':
        return ok(apply_view_mask(p.to_dict(), perms))

    if request.method == 'PUT':
        # Record-level access: super_admin or write access to this department.
        if not can_write_dept(request, p.department):
            return err('无权编辑此记录', 403, 403)
        data = _editable_payment_payload(parse_body(request), perms)
        fields, error = _parse_payment_fields(data, payment=p)
        if error:
            return err(error)
        new_dept = fields['department']
        if new_dept != p.department and not can_write_dept(request, new_dept):
            return err('无权操作目标部门', 403, 403)
        for k, v in fields.items():
            setattr(p, k, v)
        p.save()
        return ok(apply_view_mask(p.to_dict(), perms))

    if request.method == 'DELETE':
        if perms is not None:
            if not perms['can_delete']:
                return err('无删除权限', 403, 403)
            if not can_write_dept(request, p.department):
                return err('无权删除此记录', 403, 403)
        p.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


# ── dashboard ─────────────────────────────────────────────────────────────────

@pk_required()
def dashboard(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get('dashboard', True):
        return err('无访问权限', 403, 403)
    today = timezone.localdate()
    show_amount = perms is None or perms['view'].get('total_amount', True)

    base = dept_filter(Payment.objects.all(), request).annotate(paid=_paid_expr())

    def money(v):
        return str(v if v is not None else Decimal('0')) if show_amount else None

    today_qs = base.filter(planned_date=today)
    pending_qs = base.filter(paid=Decimal('0'))
    overdue_qs = base.filter(paid__lt=F('total_amount'), planned_date__lt=today)

    # Each rollup is a single count+sum aggregate (indexed, no full table load).
    today_agg = today_qs.aggregate(c=Count('id'), s=Sum('total_amount'))
    # For pending records paid=0 → remaining == total_amount.
    pending_agg = pending_qs.aggregate(c=Count('id'), s=Sum('total_amount'))
    overdue_agg = overdue_qs.aggregate(c=Count('id'), s=Sum(_remaining_expr()))
    partial_count = base.filter(paid__gt=Decimal('0'), paid__lt=F('total_amount')).count()

    today_payments = [
        apply_view_mask(p.to_dict(), perms)
        for p in today_qs.select_related('created_by')[:50]
    ]

    return ok({
        'today_count': today_agg['c'],
        'today_amount': money(today_agg['s']),
        'pending_count': pending_agg['c'],
        'pending_amount': money(pending_agg['s']),
        'partial_count': partial_count,
        'overdue_count': overdue_agg['c'],
        'overdue_amount': money(overdue_agg['s']),
        'today_payments': today_payments,
    })


# ── stats ─────────────────────────────────────────────────────────────────────

@pk_required()
def stats(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get('stats', True):
        return err('无访问权限', 403, 403)
    if perms is not None and not perms['view'].get('total_amount', True):
        return err('无金额查看权限，无法查看统计', 403, 403)
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if not (1 <= month <= 12):
            month = today.month
        if not (2000 <= year <= 2100):
            year = today.year
    except ValueError:
        year, month = today.year, today.month

    qs = Payment.objects.filter(
        planned_date__year=year, planned_date__month=month
    )
    qs = dept_filter(qs, request)

    # Optional per-department filter (user-selected; restricted by dept_filter above).
    depts_param = request.GET.get('depts', '').strip()
    if depts_param:
        selected = [d.strip() for d in depts_param.split(',') if d.strip()]
        if selected:
            qs = qs.filter(department__in=selected)

    qs = qs.annotate(paid=_paid_expr())

    D = Decimal

    # Overall totals + status breakdown in a single aggregate query.
    agg = qs.aggregate(
        total=Sum('total_amount'),
        paid_sum=Sum('paid'),
        cnt=Count('id'),
        settled=Count(Case(When(paid__gte=F('total_amount'), then=1))),
        partial=Count(Case(When(paid__gt=Decimal('0'), paid__lt=F('total_amount'), then=1))),
        pending=Count(Case(When(paid=Decimal('0'), then=1))),
    )
    total_amount = agg['total'] or D(0)
    total_paid = agg['paid_sum'] or D(0)
    total_remaining = total_amount - total_paid
    completion_rate = round(float(total_paid / total_amount * 100), 1) if total_amount else 0.0

    # Per-department rollup grouped in SQL.
    dept_rows = qs.values('department').annotate(
        total=Sum('total_amount'),
        paid_sum=Sum('paid'),
        count=Count('id'),
    ).order_by('-total')

    by_dept = []
    for r in dept_rows:
        t = r['total'] or D(0)
        pd = r['paid_sum'] or D(0)
        by_dept.append({
            'dept': r['department'],
            'total': str(t),
            'paid': str(pd),
            'remaining': str(t - pd),
            'count': r['count'],
            'completion_rate': round(float(pd / t * 100), 1) if t else 0.0,
        })

    return ok({
        'year': year, 'month': month,
        'total_amount': str(total_amount),
        'total_paid': str(total_paid),
        'total_remaining': str(total_remaining),
        'completion_rate': completion_rate,
        'total_records': agg['cnt'],
        'by_dept': by_dept,
        'by_status': {
            'settled': agg['settled'],
            'partial': agg['partial'],
            'pending': agg['pending'],
        },
    })


# ── users ─────────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required(roles=['super_admin'])
def users(request):
    if request.method == 'GET':
        try:
            all_users = PaikuanUser.objects.order_by('is_approved', 'id')
            return ok([u.to_dict() for u in all_users])
        except Exception as e:
            logger.error('users list failed: %s', e)
            return err('用户列表加载失败，请确认已执行 python manage.py migrate', 500)
    # Super admin cannot create users directly — users register themselves
    return err('请通过注册流程创建用户', 405)


@csrf_exempt
@pk_required(roles=['super_admin'])
def user_detail(request, pk):
    try:
        user = PaikuanUser.objects.get(id=pk)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)

    if request.method == 'PUT':
        data = parse_body(request)
        if 'name' in data:
            user.name = (data['name'] or '').strip()
        if 'role' in data:
            if data['role'] not in ('super_admin', 'manager', 'operator', 'viewer'):
                return err('角色无效')
            # Prevent creating a second super_admin
            if data['role'] == 'super_admin' and user.role != 'super_admin':
                return err('超级管理员只能有一位')
            # Prevent downgrading the only super_admin
            if user.role == 'super_admin' and data['role'] != 'super_admin':
                return err('不能修改超级管理员的角色')
            user.role = data['role']
        if 'departments' in data:
            depts = data['departments'] or []
            # Approved non-admin users must retain at least one department;
            # otherwise they'd become invisible to the system (no rows to see or edit).
            if user.is_approved and user.role != 'super_admin' and len(depts) == 0:
                return err('已审批用户至少需要分配一个部门')
            user.departments = depts
        if 'job_title' in data:
            user.job_title = data['job_title'] or ''
        if 'is_active' in data:
            user.is_active = bool(data['is_active'])
        if data.get('password'):
            if len(data['password']) < 6:
                return err('新密码至少6位')
            user.set_password(data['password'])
        user.save()
        return ok(user.to_dict())

    if request.method == 'DELETE':
        if user.id == request.pk_uid:
            return err('不能删除自己的账号')
        if user.role == 'super_admin':
            return err('不能删除超级管理员账号')
        user.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required(roles=['super_admin'])
def approve_user(request, pk):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    try:
        user = PaikuanUser.objects.get(id=pk)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)
    except Exception as e:
        logger.error('approve_user get failed: %s', e)
        return err('操作失败，请先执行 python manage.py migrate', 500)
    if user.role == 'super_admin':
        return err('超级管理员无需审批')
    body = parse_body(request)
    # Super admin may adjust job title / departments at approval time.
    if body.get('job_title') in JOB_TITLES:
        user.job_title = body['job_title']
    if isinstance(body.get('departments'), list):
        user.departments = body['departments']
    user.is_approved = True
    user.is_active = True
    user.role = 'operator'   # regular member; field perms come from job_title
    try:
        user.approved_by_id = request.pk_uid
        user.approved_at = timezone.now()
        user.save()
    except Exception as e:
        logger.error('approve_user save failed: %s', e)
        return err('审批保存失败，请检查数据库迁移是否完整', 500)
    return ok(user.to_dict())


@csrf_exempt
@pk_required(roles=['super_admin'])
def reject_user(request, pk):
    """Reject a pending registration by deleting the account."""
    if request.method not in ('POST', 'DELETE'):
        return err('Method not allowed', 405)
    try:
        user = PaikuanUser.objects.get(id=pk)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)
    except Exception as e:
        logger.error('reject_user get failed: %s', e)
        return err('操作失败，请先执行 python manage.py migrate', 500)
    if user.role == 'super_admin':
        return err('不能拒绝超级管理员')
    if user.is_approved:
        return err('该用户已审批，不能拒绝；如需禁用请使用停用')
    try:
        user.delete()
    except Exception as e:
        logger.error('reject_user delete failed: %s', e)
        return err('删除失败', 500)
    return ok({'rejected': pk})


# ── permissions ───────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required(roles=['super_admin'])
def permissions(request):
    """GET: full permission matrix for all job titles + field metadata."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    jobs = [
        {'job_title': key, 'label': label, 'config': get_job_perms(key)}
        for key, label in JOB_TITLES.items()
    ]
    return ok({
        'fields': PAYMENT_FIELD_DEFS,
        'pages': [
            {'key': 'dashboard', 'label': '今日工作台'},
            {'key': 'payments', 'label': '付款台账'},
            {'key': 'stats', 'label': '月度统计'},
        ],
        'jobs': jobs,
    })


@csrf_exempt
@pk_required(roles=['super_admin'])
def permission_detail(request, job):
    """PUT: update one job title's permission config."""
    if request.method != 'PUT':
        return err('Method not allowed', 405)
    if job not in JOB_TITLES:
        return err('职务无效', 404)
    body = parse_body(request)
    cfg = body.get('config') or {}

    # Sanitize against known keys to avoid storing junk.
    clean = {
        'pages': {k: bool(cfg.get('pages', {}).get(k, True)) for k in PAGE_KEYS},
        'view': {k: bool(cfg.get('view', {}).get(k, True)) for k in FIELD_KEYS},
        'edit': {k: bool(cfg.get('edit', {}).get(k, False)) for k in FIELD_KEYS},
        'can_create': bool(cfg.get('can_create', False)),
        'can_delete': bool(cfg.get('can_delete', False)),
    }
    obj, _ = JobPermission.objects.get_or_create(job_title=job)
    obj.config = clean
    obj.save()
    _invalidate_perm_cache(job)
    return ok({'job_title': job, 'config': get_job_perms(job)})


# ── Excel template / import / export ─────────────────────────────────────────

def _visible_excel_cols(perms):
    """Return [(excel_header, db_col)] for columns the user can view."""
    return [
        (h, c) for (fk, h, c) in EXCEL_COLUMN_MAP
        if perms is None or perms['view'].get(fk, True)
    ]


def _build_excel_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    # RFC 5987 encoding so Chinese filenames render correctly in all browsers.
    ascii_fallback = filename.encode('ascii', 'ignore').decode() or 'export.xlsx'
    encoded = quote(filename.encode('utf-8'), safe='')
    response['Content-Disposition'] = (
        f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
    )
    return response


@csrf_exempt
@pk_required()
def payment_template(request):
    """GET — download blank Excel import template (columns filtered by view perms)."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return err('服务器缺少 openpyxl 依赖', 500)

    cols = _visible_excel_cols(perms)

    wb = Workbook()
    ws = wb.active
    ws.title = '排款导入模板'

    header_fill = PatternFill(fill_type='solid', fgColor='C96342')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    example_font = Font(italic=True, color='888888', size=10)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # Row 1: headers
    for col_idx, (header, _) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    # Row 2: example data (grayed out). The 部门 cell carries EXAMPLE_ROW_MARKER
    # so import skips this row even if the user forgets to delete it.
    example = {
        '部门': EXAMPLE_ROW_MARKER,
        '审批单号': '如 PK202601001',
        '付款事项': '如：工程款结算',
        '收款方': '如：某某公司',
        '计划总金额(元)': 100000,
        '计划付款日期': '2026-06-01',
        '第1次付款日期': '',
        '第1次付款金额(元)': 0,
        '第2次付款日期': '',
        '第2次付款金额(元)': 0,
        '第3次付款日期': '',
        '第3次付款金额(元)': 0,
        '备注': '本行为格式示例，导入前可删除',
    }
    for col_idx, (header, _) in enumerate(cols, 1):
        cell = ws.cell(row=2, column=col_idx, value=example.get(header, ''))
        cell.font = example_font
        cell.alignment = Alignment(horizontal='left', vertical='center')

    # Column widths
    widths = {
        '部门': 14, '审批单号': 16, '付款事项': 28, '收款方': 22,
        '计划总金额(元)': 16, '计划付款日期': 14,
        '第1次付款日期': 14, '第1次付款金额(元)': 16,
        '第2次付款日期': 14, '第2次付款金额(元)': 16,
        '第3次付款日期': 14, '第3次付款金额(元)': 16,
        '备注': 24,
    }
    for col_idx, (header, _) in enumerate(cols, 1):
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = widths.get(header, 14)

    ws.row_dimensions[1].height = 22

    return _build_excel_response(wb, 'paikuan_import_template.xlsx')


@csrf_exempt
@pk_required()
def payment_import(request):
    """POST multipart/form-data with field 'file' — bulk import payments from Excel."""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    try:
        from openpyxl import load_workbook
    except ImportError:
        return err('服务器缺少 openpyxl 依赖', 500)

    if perms is not None and not perms['can_create']:
        return err('无新增权限', 403, 403)

    upload = request.FILES.get('file')
    if not upload:
        return err('请上传Excel文件(.xlsx)')

    MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
    if upload.size > MAX_UPLOAD_BYTES:
        return err('文件过大，请确认文件不超过5MB')

    try:
        wb = load_workbook(upload, read_only=True, data_only=True)
    except Exception:
        return err('文件格式有误，请使用下载的模板（.xlsx格式）')

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return err('文件为空')

    # Map header position → db column name
    header_row = [str(v).strip() if v is not None else '' for v in rows[0]]
    col_pos = {}
    for i, h in enumerate(header_row):
        if h in _EXCEL_HEADER_TO_COL:
            col_pos[_EXCEL_HEADER_TO_COL[h]] = i

    # Match the fields _parse_payment_fields actually validates as required.
    required_headers = {'department', 'project_desc', 'payee', 'planned_date'}
    missing = required_headers - set(col_pos.keys())
    if missing:
        missing_labels = [h for _, h, c in EXCEL_COLUMN_MAP if c in missing]
        return err(f'模板缺少必要列：{", ".join(missing_labels)}，请重新下载模板')

    results = {'created': 0, 'skipped': 0, 'errors': []}

    def cell_val(row, col_name):
        idx = col_pos.get(col_name)
        if idx is None or idx >= len(row):
            return None
        v = row[idx]
        # Date/datetime objects → ISO string.
        if hasattr(v, 'strftime'):
            return v.strftime('%Y-%m-%d')
        # Text dates (e.g. 2026/6/1) → normalize to ISO.
        if col_name in _EXCEL_DATE_COLS and isinstance(v, str) and v.strip():
            return _normalize_date(v)
        return v

    for row_num, row in enumerate(rows[1:], start=2):
        if all(v is None or v == '' for v in row):
            continue  # skip blank rows

        dept_raw = cell_val(row, 'department')
        if dept_raw and str(dept_raw).strip().startswith('示例'):
            continue  # template example row — skip silently

        data = {col: cell_val(row, col) for col in col_pos}

        fields, error = _parse_payment_fields(data)
        if error:
            results['errors'].append(f'第{row_num}行: {error}')
            results['skipped'] += 1
            continue

        if not can_write_dept(request, fields['department']):
            results['errors'].append(f'第{row_num}行: 无权操作部门"{fields["department"]}"')
            results['skipped'] += 1
            continue

        try:
            Payment.objects.create(created_by_id=request.pk_uid, **fields)
            results['created'] += 1
        except Exception as e:
            results['errors'].append(f'第{row_num}行: 保存失败 ({e})')
            results['skipped'] += 1

    if results['created'] > 0 and results['skipped'] == 0:
        results['message'] = f'全部 {results["created"]} 条数据成功导入'
    elif results['created'] > 0:
        results['message'] = f'成功导入 {results["created"]} 条，跳过 {results["skipped"]} 条（含错误）'
    else:
        results['message'] = f'没有可导入的数据（跳过 {results["skipped"]} 条）'
    return ok(results)


@csrf_exempt
@pk_required()
def payment_export(request):
    """GET — export filtered payment list to Excel (same filters as list view)."""
    if request.method != 'GET':
        return err('Method not allowed', 405)
    perms = get_request_perms(request)
    denied = _payments_page_denied(request, perms)
    if denied:
        return denied
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return err('服务器缺少 openpyxl 依赖', 500)

    qs = Payment.objects.select_related('created_by').all()
    qs = dept_filter(qs, request)

    dept = request.GET.get('dept', '').strip()
    status_q = request.GET.get('status', '').strip()
    start = request.GET.get('start_date', '').strip()
    end = request.GET.get('end_date', '').strip()
    q_str = request.GET.get('q', '').strip()

    if dept:
        qs = qs.filter(department=dept)
    if start:
        qs = qs.filter(planned_date__gte=start)
    if end:
        qs = qs.filter(planned_date__lte=end)
    if q_str:
        qs = qs.filter(
            Q(project_desc__icontains=q_str) | Q(payee__icontains=q_str) |
            Q(approval_number__icontains=q_str) | Q(department__icontains=q_str)
        )
    if status_q:
        qs = qs.annotate(paid=_paid_expr())
        if status_q == 'pending':
            qs = qs.filter(paid=Decimal('0'))
        elif status_q == 'settled':
            qs = qs.filter(paid__gte=F('total_amount'))
        elif status_q == 'partial':
            qs = qs.filter(paid__gt=Decimal('0'), paid__lt=F('total_amount'))

    # Reject rather than silently truncate: a truncated export is worse than no export.
    EXPORT_CAP = 5000
    total_count = qs.count()
    if total_count > EXPORT_CAP:
        return err(
            f'当前筛选结果共 {total_count} 条，超出导出上限（{EXPORT_CAP} 条）。'
            '请缩小日期范围或添加其他筛选条件后重试。'
        )

    cols = _visible_excel_cols(perms)

    wb = Workbook()
    ws = wb.active
    ws.title = '排款记录'

    header_fill = PatternFill(fill_type='solid', fgColor='C96342')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    center = Alignment(horizontal='center', vertical='center')

    for col_idx, (header, _) in enumerate(cols, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    status_label = {'pending': '⏳待付款', 'partial': '⚡部分付款', 'settled': '✅已付清'}

    _FORMULA_CHARS = ('=', '+', '-', '@', '\t', '\r')

    def _safe_text(v):
        """Prefix text cells starting with formula chars with a single-quote prefix."""
        if isinstance(v, str) and v and v[0] in _FORMULA_CHARS:
            return "'" + v
        return v

    for row_idx, p in enumerate(qs, start=2):
        d = apply_view_mask(p.to_dict(), perms)
        for col_idx, (_, db_col) in enumerate(cols, 1):
            val = d.get(db_col)
            if val is None:
                val = ''
            # Convert Decimal strings to float for Excel numeric cells
            if db_col in ('total_amount', 'pay1_amount', 'pay2_amount', 'pay3_amount',
                          'total_paid', 'remaining'):
                try:
                    val = float(val) if val != '' else 0.0
                except (ValueError, TypeError):
                    pass
            else:
                val = _safe_text(val)
            ws.cell(row=row_idx, column=col_idx, value=val)

        # Append status column after visible cols
        ws.cell(row=row_idx, column=len(cols) + 1,
                value=status_label.get(d.get('status', ''), ''))

    # Status header
    status_header_cell = ws.cell(row=1, column=len(cols) + 1, value='状态')
    status_header_cell.font = header_font
    status_header_cell.fill = header_fill
    status_header_cell.alignment = center

    # Auto-width approximation
    for col in ws.columns:
        max_len = max((len(str(c.value or '')) for c in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 32)

    today = timezone.localdate().strftime('%Y%m%d')
    return _build_excel_response(wb, f'排款记录_{today}.xlsx')


# ── departments ───────────────────────────────────────────────────────────────

@pk_required()
def departments(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    denied = _payments_page_denied(request)
    if denied:
        return denied
    # Only return canonical departments. Historical records with non-canonical names
    # (from before strict validation) should not pollute the department picker.
    merged = list(DEPARTMENTS)
    # Non-admins may only see/filter departments they are assigned to,
    # matching the row-level visibility enforced by dept_filter().
    if request.pk_role != 'super_admin':
        allowed = set(request.pk_depts or [])
        merged = [d for d in merged if d in allowed]
    return ok(merged)
