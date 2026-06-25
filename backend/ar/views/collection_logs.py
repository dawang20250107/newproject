"""催收跟进日志 CRUD — 兼容垫片（compat shim）。

历史接口，数据已统一并入 ARActivity（stage='dunning'）。本模块不再读写
旧的 ARCollectionLog 表，而是把请求转发到统一的 ARActivity 存储，并维护
ARRecord.activity_count 计数器——从而彻底消除「新面板写 ARActivity、旧接口
写 ARCollectionLog」的双写不一致。对外仍保持旧的字段形态（log_type 等），
任何老调用方（前端旧方法、外部脚本）无需改动即可继续工作。
"""
from django.db.models import F

from ._common import *  # noqa: F401,F403

from ..models import ARActivity
from paikuan.models import PaikuanUser

# 旧 log_type 仅有 5 个取值；ARActivity 多出的 system/note 在回传旧形态时归并为 other。
_LEGACY_LOG_TYPES = {'call', 'email', 'visit', 'meeting', 'other'}


def _activity_to_log_dict(a):
    """把一条 ARActivity 映射回旧『催收日志』的字段形态，保持向后兼容。"""
    log_type = a.act_type if a.act_type in _LEGACY_LOG_TYPES else 'other'
    return {
        'id': a.id,
        'ar_record_id': a.ar_record_id,
        'log_type': log_type,
        'log_type_display': dict(ARActivity.ACT_TYPE_CHOICES).get(a.act_type, a.act_type),
        'contact_person': a.contact_person,
        'note': a.note,
        'status': a.status,
        'status_display': dict(ARActivity.STATUS_CHOICES).get(a.status, a.status),
        'follow_up_date': str(a.follow_up_date) if a.follow_up_date else None,
        'created_by_id': a.created_by_id,
        'created_by_name': a.created_by.name if a.created_by else '',
        'created_at': a.created_at.isoformat() if a.created_at else None,
    }


@csrf_exempt
@pk_required()
def ar_collection_logs(request, pk):
    """GET: list dunning activities for an AR record; POST: add one."""
    try:
        ARRecord.objects.only('id').get(pk=pk)
    except ARRecord.DoesNotExist:
        return err('记录不存在', 404)
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied

    if request.method == 'GET':
        acts = (ARActivity.objects
                .filter(ar_record_id=pk, stage='dunning')
                .select_related('created_by')
                .order_by('-created_at'))
        return ok({'items': [_activity_to_log_dict(a) for a in acts]})

    if request.method == 'POST':
        data = _parse_body(request)
        log_type = (data.get('log_type') or 'call').strip()
        if log_type not in _LEGACY_LOG_TYPES:
            return err('无效的跟进类型')
        status = (data.get('status') or 'in_progress').strip()
        if status not in dict(ARActivity.STATUS_CHOICES):
            return err('无效的状态')
        note = (data.get('note') or '').strip()
        if not note:
            return err('请填写跟进内容')
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        obj = ARActivity.objects.create(
            ar_record_id=pk,
            stage='dunning',
            act_type=log_type,
            contact_person=(data.get('contact_person') or '').strip()[:100],
            note=note,
            status=status,
            follow_up_date=_normalize_date(data.get('follow_up_date')) or None,
            created_by=user,
        )
        ARRecord.objects.filter(pk=pk).update(activity_count=F('activity_count') + 1)
        return ok(_activity_to_log_dict(obj))

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_collection_log_detail(request, pk, lid):
    """PUT: edit; DELETE: remove a dunning activity (legacy log shape)."""
    try:
        obj = (ARActivity.objects
               .select_related('created_by')
               .get(pk=lid, ar_record_id=pk))
    except ARActivity.DoesNotExist:
        return err('日志不存在', 404)
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied

    is_owner = (request.pk_role == 'super_admin' or obj.created_by_id == request.pk_uid)

    if request.method == 'GET':
        return ok(_activity_to_log_dict(obj))

    if request.method == 'PUT':
        if not is_owner:
            return err('只能修改自己创建的记录', 403, 403)
        data = _parse_body(request)
        if 'log_type' in data:
            lt = (data['log_type'] or '').strip()
            if lt not in _LEGACY_LOG_TYPES:
                return err('无效的跟进类型')
            obj.act_type = lt
        if 'contact_person' in data:
            obj.contact_person = (data['contact_person'] or '').strip()[:100]
        if 'note' in data:
            note = (data['note'] or '').strip()
            if not note:
                return err('跟进内容不能为空')
            obj.note = note
        if 'status' in data:
            s = (data['status'] or '').strip()
            if s not in dict(ARActivity.STATUS_CHOICES):
                return err('无效的状态')
            obj.status = s
        if 'follow_up_date' in data:
            obj.follow_up_date = _normalize_date(data['follow_up_date']) or None
        obj.save()
        return ok(_activity_to_log_dict(obj))

    if request.method == 'DELETE':
        if not is_owner:
            return err('只能删除自己创建的记录', 403, 403)
        obj.delete()
        ARRecord.objects.filter(pk=pk).update(activity_count=F('activity_count') - 1)
        return ok({'deleted': lid})

    return err('Method not allowed', 405)
