"""催收跟进日志 CRUD — 归属于应收账款明细（ARRecord）的子资源。"""
from ._common import *  # noqa: F401,F403

from ..models import ARCollectionLog


@csrf_exempt
@pk_required()
def ar_collection_logs(request, pk):
    """GET: list logs for an AR record; POST: add a log."""
    try:
        record = ARRecord.objects.only('id').get(pk=pk)
    except ARRecord.DoesNotExist:
        return err('记录不存在', 404)
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied

    if request.method == 'GET':
        logs = (ARCollectionLog.objects
                .filter(ar_record=record)
                .select_related('created_by')
                .order_by('-created_at'))
        return ok({'items': [l.to_dict() for l in logs]})

    if request.method == 'POST':
        data = _parse_body(request)
        log_type = (data.get('log_type') or 'call').strip()
        valid_types = dict(ARCollectionLog.LOG_TYPE_CHOICES)
        if log_type not in valid_types:
            return err('无效的跟进类型')
        status = (data.get('status') or 'in_progress').strip()
        valid_statuses = dict(ARCollectionLog.STATUS_CHOICES)
        if status not in valid_statuses:
            return err('无效的状态')
        note = (data.get('note') or '').strip()
        if not note:
            return err('请填写跟进内容')
        fud = data.get('follow_up_date') or None
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        obj = ARCollectionLog.objects.create(
            ar_record=record,
            log_type=log_type,
            contact_person=(data.get('contact_person') or '').strip()[:100],
            note=note,
            status=status,
            follow_up_date=fud,
            created_by=user,
        )
        return ok(obj.to_dict())

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_collection_log_detail(request, pk, lid):
    """PUT: edit; DELETE: remove a collection log entry."""
    try:
        obj = (ARCollectionLog.objects
               .select_related('created_by')
               .get(pk=lid, ar_record_id=pk))
    except ARCollectionLog.DoesNotExist:
        return err('日志不存在', 404)
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied

    is_owner = (request.pk_role == 'super_admin' or obj.created_by_id == request.pk_uid)

    if request.method == 'GET':
        return ok(obj.to_dict())

    if request.method == 'PUT':
        if not is_owner:
            return err('只能修改自己创建的记录', 403, 403)
        data = _parse_body(request)
        valid_types = dict(ARCollectionLog.LOG_TYPE_CHOICES)
        valid_statuses = dict(ARCollectionLog.STATUS_CHOICES)
        if 'log_type' in data:
            lt = (data['log_type'] or '').strip()
            if lt not in valid_types:
                return err('无效的跟进类型')
            obj.log_type = lt
        if 'contact_person' in data:
            obj.contact_person = (data['contact_person'] or '').strip()[:100]
        if 'note' in data:
            note = (data['note'] or '').strip()
            if not note:
                return err('跟进内容不能为空')
            obj.note = note
        if 'status' in data:
            s = (data['status'] or '').strip()
            if s not in valid_statuses:
                return err('无效的状态')
            obj.status = s
        if 'follow_up_date' in data:
            obj.follow_up_date = data['follow_up_date'] or None
        obj.save()
        return ok(obj.to_dict())

    if request.method == 'DELETE':
        if not is_owner:
            return err('只能删除自己创建的记录', 403, 403)
        obj.delete()
        return ok({'deleted': lid})

    return err('Method not allowed', 405)
