import json
import logging
import datetime
import functools
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.conf import settings
from django.utils import timezone
import jwt

from paikuan.models import PaikuanUser, Payment

logger = logging.getLogger('paikuan')


# ── helpers ───────────────────────────────────────────────────────────────────

def ok(data=None):
    return JsonResponse({'code': 0, 'data': data})


def err(msg, status=400, code=-1):
    return JsonResponse({'code': code, 'error': msg}, status=status)


def parse_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return {}


def make_token(user):
    payload = {
        'uid': user.id,
        'role': user.role,
        'departments': user.departments,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        'iat': datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm='HS256')


def pk_required(roles=None):
    """JWT auth decorator. Pass roles=['super_admin'] to restrict by role."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kwargs):
            token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
            if not token:
                return err('未认证', 401, 401)
            try:
                payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])
                request.pk_uid = payload['uid']
                request.pk_role = payload['role']
                request.pk_depts = payload.get('departments', [])
            except jwt.ExpiredSignatureError:
                return err('Token已过期', 401, 401)
            except jwt.InvalidTokenError:
                return err('Token无效', 401, 401)
            if roles and request.pk_role not in roles:
                return err('权限不足', 403, 403)
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def dept_filter(qs, request):
    """Restrict queryset to user's departments for operator role."""
    if request.pk_role in ('super_admin', 'manager', 'viewer'):
        return qs
    return qs.filter(department__in=request.pk_depts)


def can_edit_payment(request, payment):
    role = request.pk_role
    if role in ('super_admin', 'manager'):
        return True
    if role == 'viewer':
        return False
    return payment.created_by_id == request.pk_uid


def can_write_dept(request, dept):
    if request.pk_role in ('super_admin', 'manager'):
        return True
    if request.pk_role == 'viewer':
        return False
    return dept in request.pk_depts


# ── auth ──────────────────────────────────────────────────────────────────────

@csrf_exempt
def register(request):
    if request.method != 'POST':
        return err('Method not allowed', 405)
    data = parse_body(request)
    phone = (data.get('phone') or '').strip()
    password = (data.get('password') or '').strip()
    name = (data.get('name') or '').strip()

    if not phone or not password or not name:
        return err('手机号、密码和姓名均必填')
    if not phone.isdigit() or len(phone) < 8:
        return err('手机号格式有误')
    if len(password) < 6:
        return err('密码至少6位')
    if PaikuanUser.objects.filter(phone=phone).exists():
        return err('该手机号已注册')

    is_first = PaikuanUser.objects.count() == 0
    user = PaikuanUser(phone=phone, name=name, role='super_admin' if is_first else 'viewer')
    user.set_password(password)
    user.save()
    return ok({'token': make_token(user), 'user': user.to_dict()})


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
        return err('账号已停用', 401, 401)
    if not user.check_password(password):
        return err('手机号或密码错误', 401, 401)
    return ok({'token': make_token(user), 'user': user.to_dict()})


@pk_required()
def me(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    try:
        user = PaikuanUser.objects.get(id=request.pk_uid)
    except PaikuanUser.DoesNotExist:
        return err('用户不存在', 404)
    return ok(user.to_dict())


# ── payments ──────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def payments(request):
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

    items = [p.to_dict() for p in qs]

    if status_q:
        items = [p for p in items if p['status'] == status_q]

    total = len(items)
    items = items[(page - 1) * size: page * size]
    return ok({'items': items, 'total': total, 'page': page, 'size': size})


def _parse_payment_fields(data, payment=None):
    """Extract and validate payment fields from request data. Returns (fields_dict, error_str)."""
    fields = {}

    def get(key, default=None):
        return data.get(key, getattr(payment, key, default) if payment else default)

    fields['department'] = (get('department') or '').strip()
    fields['approval_number'] = (get('approval_number') or '').strip()
    fields['project_desc'] = (get('project_desc') or '').strip()
    fields['payee'] = (get('payee') or '').strip()
    fields['notes'] = (get('notes') or '').strip()

    try:
        fields['total_amount'] = Decimal(str(get('total_amount', 0) or 0))
        fields['pay1_amount'] = Decimal(str(get('pay1_amount', 0) or 0))
        fields['pay2_amount'] = Decimal(str(get('pay2_amount', 0) or 0))
        fields['pay3_amount'] = Decimal(str(get('pay3_amount', 0) or 0))
    except (InvalidOperation, TypeError) as e:
        return None, f'金额格式有误: {e}'

    for key in ('planned_date', 'pay1_date', 'pay2_date', 'pay3_date'):
        val = data.get(key) if key in data else getattr(payment, key, None)
        fields[key] = val or None

    if not fields['department']:
        return None, '部门必填'
    if not fields['project_desc']:
        return None, '付款事项描述必填'
    if not fields['payee']:
        return None, '收款方必填'
    if not fields['planned_date']:
        return None, '计划付款日期必填'

    return fields, None


def _create_payment(request):
    data = parse_body(request)
    fields, error = _parse_payment_fields(data)
    if error:
        return err(error)
    if not can_write_dept(request, fields['department']):
        return err('无权操作该部门', 403, 403)
    p = Payment(created_by_id=request.pk_uid, **fields)
    p.save()
    return ok(p.to_dict())


@csrf_exempt
@pk_required()
def payment_detail(request, pk):
    try:
        p = Payment.objects.select_related('created_by').get(id=pk)
    except Payment.DoesNotExist:
        return err('记录不存在', 404)

    if not dept_filter(Payment.objects.filter(id=pk), request).exists():
        return err('无权访问', 403, 403)

    if request.method == 'GET':
        return ok(p.to_dict())

    if request.method == 'PUT':
        if not can_edit_payment(request, p):
            return err('无权编辑此记录', 403, 403)
        data = parse_body(request)
        fields, error = _parse_payment_fields(data, payment=p)
        if error:
            return err(error)
        new_dept = fields['department']
        if new_dept != p.department and not can_write_dept(request, new_dept):
            return err('无权操作目标部门', 403, 403)
        for k, v in fields.items():
            setattr(p, k, v)
        p.save()
        return ok(p.to_dict())

    if request.method == 'DELETE':
        if request.pk_role != 'super_admin':
            return err('仅超级管理员可删除', 403, 403)
        p.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


# ── dashboard ─────────────────────────────────────────────────────────────────

@pk_required()
def dashboard(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    today = timezone.localdate()
    qs = Payment.objects.select_related('created_by').all()
    qs = dept_filter(qs, request)
    items = [p.to_dict() for p in qs]

    today_str = str(today)

    def flt(cond):
        return [p for p in items if cond(p)]

    def amt(lst, field='total_amount'):
        return str(sum(Decimal(p[field]) for p in lst))

    today_items = flt(lambda p: p['planned_date'] == today_str)
    pending = flt(lambda p: p['status'] == 'pending')
    partial = flt(lambda p: p['status'] == 'partial')
    overdue = flt(lambda p: p['status'] != 'settled' and p['planned_date'] and p['planned_date'] < today_str)

    return ok({
        'today_count': len(today_items),
        'today_amount': amt(today_items),
        'pending_count': len(pending),
        'pending_amount': amt(pending, 'remaining'),
        'partial_count': len(partial),
        'overdue_count': len(overdue),
        'overdue_amount': amt(overdue, 'remaining'),
        'today_payments': today_items[:50],
    })


# ── stats ─────────────────────────────────────────────────────────────────────

@pk_required()
def stats(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
    except ValueError:
        year, month = today.year, today.month

    qs = Payment.objects.select_related('created_by').filter(
        planned_date__year=year, planned_date__month=month
    )
    qs = dept_filter(qs, request)
    items = [p.to_dict() for p in qs]

    D = Decimal
    total_amount = sum(D(p['total_amount']) for p in items)
    total_paid = sum(D(p['total_paid']) for p in items)
    total_remaining = sum(D(p['remaining']) for p in items)
    completion_rate = round(float(total_paid / total_amount * 100), 1) if total_amount else 0.0

    dept_map = {}
    for p in items:
        d = p['department']
        if d not in dept_map:
            dept_map[d] = {'dept': d, 'total': D(0), 'paid': D(0), 'remaining': D(0), 'count': 0}
        dept_map[d]['total'] += D(p['total_amount'])
        dept_map[d]['paid'] += D(p['total_paid'])
        dept_map[d]['remaining'] += D(p['remaining'])
        dept_map[d]['count'] += 1

    by_dept = sorted([
        {
            'dept': v['dept'],
            'total': str(v['total']),
            'paid': str(v['paid']),
            'remaining': str(v['remaining']),
            'count': v['count'],
            'completion_rate': round(float(v['paid'] / v['total'] * 100), 1) if v['total'] else 0.0,
        }
        for v in dept_map.values()
    ], key=lambda x: x['total'], reverse=True)

    return ok({
        'year': year,
        'month': month,
        'total_amount': str(total_amount),
        'total_paid': str(total_paid),
        'total_remaining': str(total_remaining),
        'completion_rate': completion_rate,
        'total_records': len(items),
        'by_dept': by_dept,
        'by_status': {
            'settled': sum(1 for p in items if p['status'] == 'settled'),
            'partial': sum(1 for p in items if p['status'] == 'partial'),
            'pending': sum(1 for p in items if p['status'] == 'pending'),
        },
    })


# ── users ─────────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required(roles=['super_admin'])
def users(request):
    if request.method == 'GET':
        return ok([u.to_dict() for u in PaikuanUser.objects.order_by('id')])

    if request.method == 'POST':
        data = parse_body(request)
        phone = (data.get('phone') or '').strip()
        password = (data.get('password') or '').strip()
        name = (data.get('name') or '').strip()
        role = (data.get('role') or 'operator').strip()
        departments = data.get('departments') or []

        if not phone or not password or not name:
            return err('手机号、密码和姓名均必填')
        if role not in ('super_admin', 'manager', 'operator', 'viewer'):
            return err('角色无效')
        if PaikuanUser.objects.filter(phone=phone).exists():
            return err('该手机号已注册')

        user = PaikuanUser(phone=phone, name=name, role=role, departments=departments)
        user.set_password(password)
        user.save()
        return ok(user.to_dict())

    return err('Method not allowed', 405)


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
            user.role = data['role']
        if 'departments' in data:
            user.departments = data['departments'] or []
        if 'is_active' in data:
            user.is_active = bool(data['is_active'])
        if data.get('password'):
            user.set_password(data['password'])
        user.save()
        return ok(user.to_dict())

    if request.method == 'DELETE':
        if user.id == request.pk_uid:
            return err('不能停用自己的账号')
        user.is_active = False
        user.save()
        return ok({'deactivated': pk})

    return err('Method not allowed', 405)


# ── departments ───────────────────────────────────────────────────────────────

@pk_required()
def departments(request):
    if request.method != 'GET':
        return err('Method not allowed', 405)
    depts = list(
        Payment.objects.values_list('department', flat=True)
        .distinct().order_by('department')
    )
    return ok(depts)
