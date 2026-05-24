import io
import json
import logging
import datetime
import functools
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Sum, Q
from django.conf import settings
from django.utils import timezone
import jwt

from caiwu.models import (
    CaiwuUser, L1Category, L2Category, L3Category,
    ImportBatch, FinancialEntry,
    BUSINESS_UNITS, VALID_BUSINESS_UNITS, ROLES, JOB_TITLES, ALL_BU_ROLES,
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
            if roles and request.cw_role not in roles:
                return err('权限不足', 403, 403)
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def _bu_filter(qs, request):
    """Filter queryset by business_unit based on role."""
    if request.cw_role in ALL_BU_ROLES:
        return qs
    return qs.filter(business_unit__in=request.cw_depts)


def _can_access_bu(request, bu):
    if request.cw_role in ALL_BU_ROLES:
        return True
    return bu in request.cw_depts


def _can_upload(request):
    return request.cw_role in ('super_admin', 'manager', 'operator')


def _can_publish(request):
    return request.cw_role in ('super_admin', 'manager')


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
    departments = body.get('departments', [])

    if not phone or not password or not name:
        return err('手机号、密码、姓名均为必填')
    if len(password) < 6:
        return err('密码至少6位')
    if not name.strip():
        return err('姓名不能为空')
    if CaiwuUser.objects.filter(phone=phone).exists():
        return err('该手机号已注册')

    is_first = not CaiwuUser.objects.exists()
    user = CaiwuUser(
        phone=phone,
        name=name,
        role='super_admin' if is_first else 'viewer',
        job_title=job_title if job_title in JOB_TITLES else '',
        departments=departments if is_first else [],
        is_approved=is_first,
    )
    user.set_password(password)
    user.save()

    if is_first:
        token = _make_token(user)
        return ok({'token': token, 'user': user.to_dict(), 'permissions': _build_perms(user)})
    return ok({'pending': True, 'msg': '注册成功，等待管理员审批'})


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
    return ok({'token': token, 'user': user.to_dict(), 'permissions': _build_perms(user)})


@cw_required()
def me(request):
    if request.method != 'GET':
        return err('方法不允许', 405)
    try:
        user = CaiwuUser.objects.get(id=request.cw_uid)
    except CaiwuUser.DoesNotExist:
        return err('用户不存在', 404)
    token = _make_token(user)
    return ok({'token': token, 'user': user.to_dict(), 'permissions': _build_perms(user)})


def _build_perms(user):
    is_admin = user.role == 'super_admin'
    can_upload = user.role in ('super_admin', 'manager', 'operator')
    can_publish = user.role in ('super_admin', 'manager')
    can_delete = user.role == 'super_admin'
    return {
        'is_admin': is_admin,
        'can_upload': can_upload,
        'can_publish': can_publish,
        'can_delete': can_delete,
        'pages': {
            'report': True,
            'data': can_upload,
            'charts': True,
            'settings': is_admin,
        },
    }


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
        if role not in ROLES:
            return err('角色无效')
        if CaiwuUser.objects.filter(phone=phone).exists():
            return err('该手机号已注册')

        approver = CaiwuUser.objects.get(id=request.cw_uid)
        user = CaiwuUser(
            phone=phone, name=name, role=role,
            job_title=job_title if job_title in JOB_TITLES else '',
            departments=departments,
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
        role = (body.get('role') or user.role).strip()
        if role not in ROLES:
            return err('角色无效')
        job_title = (body.get('job_title') or '').strip()
        departments = body.get('departments', user.departments)

        if role not in ALL_BU_ROLES and not departments:
            return err('非全局角色必须分配至少一个事业部')

        user.name = name
        user.role = role
        user.job_title = job_title if job_title in JOB_TITLES else ''
        user.departments = departments
        user.is_active = bool(body.get('is_active', user.is_active))

        if 'password' in body and body['password']:
            pw = str(body['password']).strip()
            if len(pw) < 6:
                return err('密码至少6位')
            user.set_password(pw)

        user.save()
        return ok(user.to_dict())

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
    role = (body.get('role') or 'viewer').strip()
    if role not in ROLES:
        return err('角色无效')
    departments = body.get('departments', [])
    if role not in ALL_BU_ROLES and not departments:
        return err('非全局角色必须分配至少一个事业部')

    approver = CaiwuUser.objects.get(id=request.cw_uid)
    user.role = role
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

    # Validate headers
    headers = [str(ws.cell(row=1, column=c).value or '').strip() for c in range(1, 5)]
    if headers != EXCEL_HEADERS:
        return err(f'表头不符合模板格式，期望：{EXCEL_HEADERS}，实际：{headers}')

    # Load all L1 categories for matching
    l1_map = {c.name: c for c in L1Category.objects.all()}
    if not l1_map:
        return err('系统尚未配置一级科目，请先在「设置」中添加一级科目')

    # Load existing L2/L3 for this BU (will auto-create missing)
    l2_map = {c.name: c for c in L2Category.objects.filter(business_unit=bu)}
    # L3 map keyed by (l1_id_or_None, name)
    l3_map = {(c.l1_category_id, c.name): c for c in L3Category.objects.filter(business_unit=bu)}

    errors = []
    preview_rows = []
    parsed_rows = []

    for row_idx in range(2, ws.max_row + 1):
        l1_name = str(ws.cell(row=row_idx, column=1).value or '').strip()
        l2_name = str(ws.cell(row=row_idx, column=2).value or '').strip()
        l3_name = str(ws.cell(row=row_idx, column=3).value or '').strip()
        amt_raw = ws.cell(row=row_idx, column=4).value

        if not l1_name and not l2_name and not l3_name and amt_raw is None:
            continue  # skip blank rows

        if not l1_name:
            errors.append(f'第{row_idx}行：一级科目不能为空')
            continue
        if l1_name not in l1_map:
            errors.append(f'第{row_idx}行：一级科目"{l1_name}"不存在，请先在设置中添加')
            continue
        if l1_map[l1_name].is_calculated:
            errors.append(f'第{row_idx}行："{l1_name}"是计算行（由系统自动推算），不能直接导入数据')
            continue

        try:
            amount = Decimal(str(amt_raw))
        except (InvalidOperation, TypeError):
            errors.append(f'第{row_idx}行：金额"{amt_raw}"格式错误')
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
            l1_id = l1.id
            key = (l1_id, l3_name)
            if key not in l3_map:
                l3_obj = L3Category(
                    business_unit=bu, l1_category=l1, name=l3_name,
                    sort_order=len(l3_map),
                )
                l3_obj.save()
                l3_map[key] = l3_obj
            l3 = l3_map[key]

        parsed_rows.append({
            'l1': l1, 'l2': l2, 'l3': l3, 'amount': amount,
            'l1_name': l1_name, 'l2_name': l2_name, 'l3_name': l3_name,
        })
        if len(preview_rows) < 10:
            preview_rows.append({
                'l1': l1_name, 'l2': l2_name, 'l3': l3_name,
                'amount': float(amount),
            })

    if errors:
        return err(f'文件存在{len(errors)}处错误：' + '；'.join(errors[:5]) + ('…' if len(errors) > 5 else ''))

    if not parsed_rows:
        return err('文件中没有有效数据行')

    # Create draft batch
    uploader = CaiwuUser.objects.get(id=request.cw_uid)
    batch = ImportBatch.objects.create(
        business_unit=bu,
        year=year,
        month=month,
        status=ImportBatch.STATUS_DRAFT,
        uploaded_by=uploader,
        row_count=len(parsed_rows),
        file_name=f.name,
    )
    entries = [
        FinancialEntry(
            batch=batch,
            l1=r['l1'], l2=r['l2'], l3=r['l3'],
            amount=r['amount'],
        )
        for r in parsed_rows
    ]
    FinancialEntry.objects.bulk_create(entries)

    return ok({
        'batch': batch.to_dict(),
        'preview': preview_rows,
        'row_count': len(parsed_rows),
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

    # Retire any previously published batch for same BU+month
    old_published = ImportBatch.objects.filter(
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
        if request.cw_role != 'super_admin':
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

    l1_cats = list(L1Category.objects.all())

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

    year_s = request.GET.get('year', '')
    month_s = request.GET.get('month', '')
    bu_param = request.GET.get('bu', '')
    try:
        level = int(request.GET.get('level', '1'))
        assert level in (1, 2, 3)
    except Exception:
        level = 1

    try:
        year = int(year_s)
        month = int(month_s)
        assert 2000 <= year <= 2100 and 1 <= month <= 12
    except Exception:
        return err('年份或月份无效')

    # Determine accessible BUs
    if request.cw_role in ALL_BU_ROLES:
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

    year_s = request.GET.get('year', '')
    month_s = request.GET.get('month', '')
    bu_param = request.GET.get('bu', '')
    try:
        level = int(request.GET.get('level', '1'))
        assert level in (1, 2, 3)
    except Exception:
        level = 1

    try:
        year = int(year_s)
        month = int(month_s)
        assert 2000 <= year <= 2100 and 1 <= month <= 12
    except Exception:
        return err('年份或月份无效')

    if request.cw_role in ALL_BU_ROLES:
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
