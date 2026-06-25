"""筛选方案（filter schemes）业务域：命名保存高级筛选条件，私有/公共（团队共享）。
对标金蝶云星空「过滤方案」。共享基座来自 _common。"""
import json as _json

from ._common import *  # noqa: F401,F403
from ar.models import ARFilterScheme, ARSchemeDefault

# 单用户方案数量上限（私有+创建的公共合计），防滥建
_SCHEME_LIMIT = 100
_VALID_MODULES = {'ar_records'}
_VALID_SCOPES = {'private', 'public'}


def _visible_schemes(request, module):
    """当前用户可见的方案：自己的私有 + 全部公共（同 module）。"""
    return ARFilterScheme.objects.select_related('owner').filter(
        Q(module=module) & (Q(scope='public') | Q(owner_id=request.pk_uid)))


def _can_manage(request, obj):
    """可改/删：本人，或超管（对公共方案做治理）。"""
    return request.pk_role == 'super_admin' or obj.owner_id == request.pk_uid


def _clean_conditions(raw):
    """把条件快照规整成 JSON 字符串；非法输入退化为空数组（不报错）。"""
    if isinstance(raw, str):
        try:
            raw = _json.loads(raw)
        except (ValueError, TypeError):
            raw = []
    if not isinstance(raw, list):
        raw = []
    return _json.dumps(raw, ensure_ascii=False)


@csrf_exempt
@pk_required()
def ar_filter_schemes(request):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    module = (request.GET.get('module') or 'ar_records').strip()
    if module not in _VALID_MODULES:
        return err('未知列表', 400)

    if request.method == 'GET':
        # 当前用户在该列表的默认方案（跟随账号）→ 标注 is_default
        default_id = (ARSchemeDefault.objects
                      .filter(user_id=request.pk_uid, module=module)
                      .values_list('scheme_id', flat=True).first())
        rows = []
        for s in _visible_schemes(request, module):
            d = s.to_dict()
            d['is_default'] = (s.id == default_id)
            rows.append(d)
        return ok({'items': rows, 'default_id': default_id})

    if request.method == 'POST':
        data = _parse_body(request)
        name = (data.get('name') or '').strip()
        if not name:
            return err('请填写方案名称')
        if len(name) > 40:
            return err('方案名称过长（≤40 字）')
        scope = (data.get('scope') or 'private').strip()
        if scope not in _VALID_SCOPES:
            return err('无效的可见范围')
        # 公共方案=团队共享，需写权限（治理）；私有方案任何可见应收的用户均可存
        if scope == 'public':
            d = _write_denied(request)
            if d:
                return err('仅有写入权限的用户可创建公共方案', 403, 403)
        if ARFilterScheme.objects.filter(owner_id=request.pk_uid).count() >= _SCHEME_LIMIT:
            return err(f'方案数量已达上限（{_SCHEME_LIMIT}），请先删除部分方案')
        # 同名（同 module + 同 scope + 同 owner）覆盖更新，避免重复堆积
        from paikuan.models import PaikuanUser
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        obj, _created = ARFilterScheme.objects.update_or_create(
            owner_id=request.pk_uid, module=module, scope=scope, name=name,
            defaults={
                'conditions': _clean_conditions(data.get('conditions')),
                'match': 'any' if data.get('match') == 'any' else 'all',
                'owner': user,
            })
        return ok(obj.to_dict())

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_filter_scheme_detail(request, pk):
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    try:
        obj = ARFilterScheme.objects.select_related('owner').get(pk=pk)
    except ARFilterScheme.DoesNotExist:
        return err('方案不存在', 404)
    # 可见性：公共，或本人私有
    if obj.scope != 'public' and obj.owner_id != request.pk_uid:
        return err('无权访问此方案', 403, 403)

    if request.method == 'GET':
        return ok(obj.to_dict())

    if request.method == 'PUT':
        if not _can_manage(request, obj):
            return err('只能修改自己创建的方案', 403, 403)
        data = _parse_body(request)
        if 'name' in data:
            name = (data.get('name') or '').strip()
            if not name:
                return err('请填写方案名称')
            obj.name = name[:40]
        if 'scope' in data:
            scope = (data.get('scope') or '').strip()
            if scope not in _VALID_SCOPES:
                return err('无效的可见范围')
            # 升级为公共需写权限
            if scope == 'public' and obj.scope != 'public':
                d = _write_denied(request)
                if d:
                    return err('仅有写入权限的用户可发布公共方案', 403, 403)
            obj.scope = scope
        if 'conditions' in data:
            obj.conditions = _clean_conditions(data.get('conditions'))
        if 'match' in data:
            obj.match = 'any' if data.get('match') == 'any' else 'all'
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
def ar_filter_scheme_default(request):
    """设/取消「默认方案」（跟随账号，按列表唯一）。
    body: {scheme_id: <id> | null, module}。scheme_id 为空 → 取消默认。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('Method not allowed', 405)
    data = _parse_body(request)
    module = (data.get('module') or 'ar_records').strip()
    if module not in _VALID_MODULES:
        return err('未知列表', 400)
    sid = data.get('scheme_id')
    # 取消默认
    if sid in (None, '', 0, '0'):
        ARSchemeDefault.objects.filter(user_id=request.pk_uid, module=module).delete()
        return ok({'default_id': None})
    # 设默认：方案须对当前用户可见（本人私有 或 公共）
    try:
        obj = ARFilterScheme.objects.get(pk=int(sid), module=module)
    except (ARFilterScheme.DoesNotExist, TypeError, ValueError):
        return err('方案不存在', 404)
    if obj.scope != 'public' and obj.owner_id != request.pk_uid:
        return err('无权将此方案设为默认', 403, 403)
    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    ARSchemeDefault.objects.update_or_create(
        user=user, module=module, defaults={'scheme': obj})
    return ok({'default_id': obj.id})
