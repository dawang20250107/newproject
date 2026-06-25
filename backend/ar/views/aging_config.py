"""账龄分桶边界配置 API — 全局单条，超管可改。"""
from ._common import *  # noqa
from ..models import AgingBucketConfig


@csrf_exempt
@pk_required()
def ar_aging_config(request):
    """GET: 取当前配置; PUT: 超管更新。"""
    if request.method == 'GET':
        return ok(AgingBucketConfig.get_or_default())

    if request.method == 'PUT':
        if request.pk_role != 'super_admin':
            return err('仅超管可修改账龄分桶配置', 403, 403)
        data = _parse_body(request)
        b1 = int(data.get('bucket1') or 30)
        b2 = int(data.get('bucket2') or 60)
        b3 = int(data.get('bucket3') or 90)
        if not (0 < b1 < b2 < b3):
            return err('桶边界须满足 0 < 桶1 < 桶2 < 桶3')
        from paikuan.models import PaikuanUser
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        obj, _ = AgingBucketConfig.objects.get_or_create(pk=1, defaults={
            'bucket1': b1, 'bucket2': b2, 'bucket3': b3, 'updated_by': user,
        })
        if _:
            pass  # just created
        else:
            obj.bucket1 = b1; obj.bucket2 = b2; obj.bucket3 = b3
            obj.updated_by = user; obj.save()
        return ok(obj.to_dict())

    return err('Method not allowed', 405)
