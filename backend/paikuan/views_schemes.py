"""通用「列表筛选方案」基座视图：保存任意列表页的列头筛选 + 排序快照，
私有/公共团队共享 + 默认方案（跟随账号）。面向所有用 ColumnFilter 的列表页复用。

权限按 module 映射到对应页面权限位；helpers 复用 paikuan.views。"""
import json as _json

from django.views.decorators.csrf import csrf_exempt

from .models import ListScheme, ListSchemeDefault, PaikuanUser
from .views import ok, err, parse_body, pk_required, get_request_perms

# module → 页面权限位（perms['pages'][key]）。新增列表页在此登记即可启用方案能力。
_MODULE_PAGE = {
    'pk_payments': 'payments',
    'pk_approvals': 'approval_records',
}
_SCHEME_LIMIT = 100
_VALID_SCOPES = {'private', 'public'}


def _module_denied(request, module):
    """列表页访问权限（按 module 映射）。未登记的 module → 400。"""
    page = _MODULE_PAGE.get(module)
    if not page:
        return err('未知列表', 400)
    perms = get_request_perms(request)
    if perms is not None and not perms['pages'].get(page, True):
        return err('无访问权限', 403, 403)
    return None


def _can_create_public(request):
    """公共方案=团队共享，需写权限（治理）。super_admin(perms=None) 放行。"""
    perms = get_request_perms(request)
    return perms is None or perms.get('can_create', False)


def _can_manage(request, obj):
    return request.pk_role == 'super_admin' or obj.owner_id == request.pk_uid


def _clean_payload(raw):
    """状态快照规整为 JSON 字符串；非法输入退化为空对象（不报错）。"""
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except (ValueError, TypeError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return _json.dumps(raw, ensure_ascii=False)


@csrf_exempt
@pk_required()
def list_schemes(request):
    module = (request.GET.get('module') or request.GET.get('m') or '').strip()
    if not module and request.method != 'GET':
        module = (parse_body(request).get('module') or '').strip()
    denied = _module_denied(request, module)
    if denied:
        return denied

    if request.method == 'GET':
        from django.db.models import Q
        qs = (ListScheme.objects.select_related('owner')
              .filter(Q(module=module) & (Q(scope='public') | Q(owner_id=request.pk_uid))))
        default_id = (ListSchemeDefault.objects
                      .filter(user_id=request.pk_uid, module=module)
                      .values_list('scheme_id', flat=True).first())
        rows = []
        for s in qs:
            d = s.to_dict()
            d['is_default'] = (s.id == default_id)
            rows.append(d)
        return ok({'items': rows, 'default_id': default_id})

    if request.method == 'POST':
        data = parse_body(request)
        name = (data.get('name') or '').strip()
        if not name:
            return err('请填写方案名称')
        if len(name) > 40:
            return err('方案名称过长（≤40 字）')
        scope = (data.get('scope') or 'private').strip()
        if scope not in _VALID_SCOPES:
            return err('无效的可见范围')
        if scope == 'public' and not _can_create_public(request):
            return err('仅有写入权限的用户可创建公共方案', 403, 403)
        if ListScheme.objects.filter(owner_id=request.pk_uid).count() >= _SCHEME_LIMIT:
            return err(f'方案数量已达上限（{_SCHEME_LIMIT}），请先删除部分方案')
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        obj, _created = ListScheme.objects.update_or_create(
            owner_id=request.pk_uid, module=module, scope=scope, name=name,
            defaults={'payload': _clean_payload(data.get('payload')), 'owner': user})
        return ok(obj.to_dict())

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def list_scheme_detail(request, pk):
    try:
        obj = ListScheme.objects.select_related('owner').get(pk=pk)
    except ListScheme.DoesNotExist:
        return err('方案不存在', 404)
    denied = _module_denied(request, obj.module)
    if denied:
        return denied
    if obj.scope != 'public' and obj.owner_id != request.pk_uid:
        return err('无权访问此方案', 403, 403)

    if request.method == 'GET':
        return ok(obj.to_dict())

    if request.method == 'PUT':
        if not _can_manage(request, obj):
            return err('只能修改自己创建的方案', 403, 403)
        data = parse_body(request)
        if 'name' in data:
            name = (data.get('name') or '').strip()
            if not name:
                return err('请填写方案名称')
            obj.name = name[:40]
        if 'scope' in data:
            scope = (data.get('scope') or '').strip()
            if scope not in _VALID_SCOPES:
                return err('无效的可见范围')
            if scope == 'public' and obj.scope != 'public' and not _can_create_public(request):
                return err('仅有写入权限的用户可发布公共方案', 403, 403)
            obj.scope = scope
        if 'payload' in data:
            obj.payload = _clean_payload(data.get('payload'))
        obj.save()
        return ok(obj.to_dict())

    if request.method == 'DELETE':
        if not _can_manage(request, obj):
            return err('只能删除自己创建的方案', 403, 403)
        obj.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def list_scheme_default(request):
    """设/取消默认方案（跟随账号，按 module 唯一）。body: {scheme_id|null, module}。"""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    data = parse_body(request)
    module = (data.get('module') or '').strip()
    denied = _module_denied(request, module)
    if denied:
        return denied
    sid = data.get('scheme_id')
    if sid in (None, '', 0, '0'):
        ListSchemeDefault.objects.filter(user_id=request.pk_uid, module=module).delete()
        return ok({'default_id': None})
    try:
        obj = ListScheme.objects.get(pk=int(sid), module=module)
    except (ListScheme.DoesNotExist, TypeError, ValueError):
        return err('方案不存在', 404)
    if obj.scope != 'public' and obj.owner_id != request.pk_uid:
        return err('无权将此方案设为默认', 403, 403)
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    ListSchemeDefault.objects.update_or_create(
        user=user, module=module, defaults={'scheme': obj})
    return ok({'default_id': obj.id})
