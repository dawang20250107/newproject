"""应收动态（ARActivity）+ 附件（ARAttachment）CRUD。"""
import os
import mimetypes
from django.conf import settings
from django.db.models import F
from django.http import FileResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from ._common import *  # noqa: F401,F403
from ..models import ARActivity, ARAttachment
from paikuan.models import PaikuanUser


# ── 允许的文件扩展名 ──────────────────────────────────────────────────────────
_ALLOWED_EXTS = ARAttachment.ALLOWED_EXTS
_IMAGE_EXTS = ARAttachment.IMAGE_EXTS
_MAX_BYTES = getattr(settings, 'UPLOAD_MAX_MB', 20) * 1024 * 1024


def _thumb_path_for(file_path):
    """Given upload path like 'ar/1/abcdef.jpg', return 'ar/1/thumbs/abcdef.jpg'."""
    d = os.path.dirname(file_path)
    fname = os.path.basename(file_path)
    return os.path.join(d, 'thumbs', fname.rsplit('.', 1)[0] + '.jpg')


def _generate_thumb(src_abs, thumb_abs):
    """Generate JPEG thumbnail. Returns True on success (Pillow optional)."""
    try:
        from PIL import Image
        os.makedirs(os.path.dirname(thumb_abs), exist_ok=True)
        with Image.open(src_abs) as img:
            img.thumbnail((320, 320), Image.LANCZOS)
            rgb = img.convert('RGB')
            rgb.save(thumb_abs, 'JPEG', quality=75, optimize=True)
        return True
    except Exception:
        return False


def _get_record_or_403(request, pk):
    """Return (record, err_response). Handles 404 + dept access check."""
    try:
        rec = ARRecord.objects.only(
            'id', 'delivery_dept', 'activity_count', 'attachment_count'
        ).get(pk=pk)
    except ARRecord.DoesNotExist:
        return None, err('记录不存在', 404)
    if request.pk_role != 'super_admin':
        if rec.delivery_dept not in request.pk_depts:
            return None, err('无权访问', 403)
    return rec, None


# ── 动态列表 + 新增 ──────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def ar_activity_list(request, pk):
    """
    GET  /records/{pk}/activity  -> combined { activities, attachments }
    POST /records/{pk}/activity  -> add activity
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    rec, err_resp = _get_record_or_403(request, pk)
    if err_resp:
        return err_resp

    if request.method == 'GET':
        stage = request.GET.get('stage', '')
        qs_act = (ARActivity.objects
                  .filter(ar_record_id=pk)
                  .select_related('created_by')
                  .order_by('-created_at'))
        if stage:
            qs_act = qs_act.filter(stage=stage)
        qs_att = (ARAttachment.objects
                  .filter(ar_record_id=pk)
                  .select_related('uploaded_by')
                  .order_by('-created_at'))
        if stage:
            qs_att = qs_att.filter(stage=stage)
        uid = request.pk_uid
        role = request.pk_role
        return ok({
            'activities': [a.to_dict(request_uid=uid, request_role=role) for a in qs_act],
            'attachments': [a.to_dict(record_id=pk) for a in qs_att],
        })

    if request.method == 'POST':
        denied_w = _write_denied(request)
        if denied_w:
            return denied_w
        data = _parse_body(request)
        stage = (data.get('stage') or 'dunning').strip()
        valid_stages = dict(ARActivity.STAGE_CHOICES)
        if stage not in valid_stages:
            return err('无效的阶段')
        act_type = (data.get('act_type') or 'call').strip()
        if act_type not in dict(ARActivity.ACT_TYPE_CHOICES):
            return err('无效的类型')
        note = (data.get('note') or '').strip()
        if not note:
            return err('请填写内容')
        status = (data.get('status') or 'in_progress').strip()
        if status not in dict(ARActivity.STATUS_CHOICES):
            return err('无效的状态')
        user = PaikuanUser.objects.filter(id=request.pk_uid).first()
        obj = ARActivity.objects.create(
            ar_record_id=pk,
            stage=stage,
            act_type=act_type,
            contact_person=(data.get('contact_person') or '').strip()[:100],
            note=note,
            status=status,
            follow_up_date=_normalize_date(data.get('follow_up_date')) or None,
            created_by=user,
        )
        # increment counter atomically
        ARRecord.objects.filter(pk=pk).update(activity_count=F('activity_count') + 1)
        return ok(obj.to_dict(request_uid=request.pk_uid, request_role=request.pk_role))

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_activity_detail(request, pk, aid):
    """PUT/DELETE /records/{pk}/activity/{aid}"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    _, err_resp = _get_record_or_403(request, pk)
    if err_resp:
        return err_resp
    try:
        obj = (ARActivity.objects
               .select_related('created_by')
               .get(pk=aid, ar_record_id=pk))
    except ARActivity.DoesNotExist:
        return err('动态不存在', 404)

    is_owner = (request.pk_role == 'super_admin' or obj.created_by_id == request.pk_uid)

    if request.method == 'PUT':
        if not is_owner:
            return err('只能修改自己创建的记录', 403)
        data = _parse_body(request)
        if 'stage' in data:
            s = (data['stage'] or '').strip()
            if s not in dict(ARActivity.STAGE_CHOICES):
                return err('无效的阶段')
            obj.stage = s
        if 'act_type' in data:
            t = (data['act_type'] or '').strip()
            if t not in dict(ARActivity.ACT_TYPE_CHOICES):
                return err('无效的类型')
            obj.act_type = t
        if 'contact_person' in data:
            obj.contact_person = (data['contact_person'] or '').strip()[:100]
        if 'note' in data:
            n = (data['note'] or '').strip()
            if not n:
                return err('内容不能为空')
            obj.note = n
        if 'status' in data:
            s = (data['status'] or '').strip()
            if s not in dict(ARActivity.STATUS_CHOICES):
                return err('无效的状态')
            obj.status = s
        if 'follow_up_date' in data:
            obj.follow_up_date = _normalize_date(data['follow_up_date']) or None
        obj.save()
        return ok(obj.to_dict(request_uid=request.pk_uid, request_role=request.pk_role))

    if request.method == 'DELETE':
        if not is_owner:
            return err('只能删除自己创建的记录', 403)
        obj.delete()
        ARRecord.objects.filter(pk=pk).update(
            activity_count=F('activity_count') - 1
        )
        return ok({'deleted': aid})

    return err('Method not allowed', 405)


# ── 附件上传 / 下载 / 删除 ───────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def ar_attachment_list(request, pk):
    """POST /records/{pk}/attachments -- upload a file."""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    denied_w = _write_denied(request)
    if denied_w:
        return denied_w
    _, err_resp = _get_record_or_403(request, pk)
    if err_resp:
        return err_resp

    if request.method != 'POST':
        return err('Method not allowed', 405)

    f = request.FILES.get('file')
    if not f:
        return err('缺少文件')

    # size check
    if f.size > _MAX_BYTES:
        return err(f'文件不能超过 {settings.UPLOAD_MAX_MB}MB（当前 {f.size // 1048576}MB）')

    # extension check
    original_name = f.name or 'file'
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in _ALLOWED_EXTS:
        return err(f'不支持的文件格式：{ext}。支持：图片/PDF/Excel/Word/CSV/TXT')

    stage = (request.POST.get('stage') or 'general').strip()
    if stage not in dict(ARActivity.STAGE_CHOICES):
        stage = 'general'
    activity_id = request.POST.get('activity_id') or None

    user = PaikuanUser.objects.filter(id=request.pk_uid).first()
    mime_type = mimetypes.guess_type(original_name)[0] or 'application/octet-stream'

    obj = ARAttachment(
        ar_record_id=pk,
        stage=stage,
        activity_id=activity_id,
        file_name=original_name[:255],
        file_size=f.size,
        mime_type=mime_type,
        uploaded_by=user,
    )
    obj.file = f  # Django FileField handles moving to MEDIA_ROOT/_attachment_upload_path
    obj.save()

    # Generate thumbnail for images
    if ext in _IMAGE_EXTS:
        media_root = settings.MEDIA_ROOT
        src_abs = os.path.join(str(media_root), str(obj.file))
        rel_thumb = _thumb_path_for(str(obj.file))
        thumb_abs = os.path.join(str(media_root), rel_thumb)
        if _generate_thumb(src_abs, thumb_abs):
            ARAttachment.objects.filter(pk=obj.pk).update(thumb_path=rel_thumb)
            obj.thumb_path = rel_thumb

    ARRecord.objects.filter(pk=pk).update(attachment_count=F('attachment_count') + 1)
    return ok(obj.to_dict(record_id=pk))


@csrf_exempt
@pk_required()
def ar_attachment_detail(request, pk, fid):
    """GET /records/{pk}/attachments/{fid} -- download.
       DELETE /records/{pk}/attachments/{fid} -- delete."""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    _, err_resp = _get_record_or_403(request, pk)
    if err_resp:
        return err_resp
    try:
        obj = ARAttachment.objects.select_related('uploaded_by').get(pk=fid, ar_record_id=pk)
    except ARAttachment.DoesNotExist:
        return err('附件不存在', 404)

    if request.method == 'GET':
        x_accel_base = getattr(settings, 'X_ACCEL_REDIRECT_BASE', '')
        if x_accel_base:
            resp = HttpResponse()
            resp['X-Accel-Redirect'] = x_accel_base + str(obj.file)
            resp['Content-Type'] = obj.mime_type or 'application/octet-stream'
            resp['Content-Disposition'] = f'attachment; filename="{obj.file_name}"'
            return resp
        try:
            return FileResponse(
                obj.file.open('rb'),
                as_attachment=True,
                filename=obj.file_name,
            )
        except FileNotFoundError:
            return err('文件已不存在，请重新上传', 404)

    if request.method == 'DELETE':
        denied_w = _write_denied(request)
        if denied_w:
            return denied_w
        is_owner = (request.pk_role == 'super_admin'
                    or obj.uploaded_by_id == request.pk_uid)
        if not is_owner:
            return err('只能删除自己上传的附件', 403)
        # delete physical files
        try:
            media_root = str(settings.MEDIA_ROOT)
            file_abs = os.path.join(media_root, str(obj.file))
            if os.path.exists(file_abs):
                os.remove(file_abs)
            if obj.thumb_path:
                thumb_abs = os.path.join(media_root, obj.thumb_path)
                if os.path.exists(thumb_abs):
                    os.remove(thumb_abs)
        except Exception:
            pass
        obj.delete()
        ARRecord.objects.filter(pk=pk).update(
            attachment_count=F('attachment_count') - 1
        )
        return ok({'deleted': fid})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_attachment_thumb(request, pk, fid):
    """GET /records/{pk}/attachments/{fid}/thumb -- serve thumbnail."""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    _, err_resp = _get_record_or_403(request, pk)
    if err_resp:
        return err_resp
    try:
        obj = ARAttachment.objects.only('thumb_path', 'file_name').get(pk=fid, ar_record_id=pk)
    except ARAttachment.DoesNotExist:
        return err('附件不存在', 404)
    if not obj.thumb_path:
        return err('暂无缩略图', 404)
    try:
        media_root = str(settings.MEDIA_ROOT)
        thumb_abs = os.path.join(media_root, obj.thumb_path)
        return FileResponse(open(thumb_abs, 'rb'), content_type='image/jpeg')
    except FileNotFoundError:
        return err('缩略图文件不存在', 404)


# ── 快速行内编辑 ─────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def ar_record_quick_edit(request, pk):
    """PATCH /records/{pk}/quick-edit -- inline edit collector / target_collection_date / notes."""
    if request.method != 'PATCH':
        return err('Method not allowed', 405)
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    denied_w = _write_denied(request)
    if denied_w:
        return denied_w
    _, err_resp = _get_record_or_403(request, pk)
    if err_resp:
        return err_resp

    try:
        rec = ARRecord.objects.get(pk=pk)
    except ARRecord.DoesNotExist:
        return err('记录不存在', 404)

    data = _parse_body(request)
    updated = {}
    if 'collector' in data:
        rec.collector = (data['collector'] or '').strip()[:100]
        updated['collector'] = rec.collector
    if 'target_collection_date' in data:
        rec.target_collection_date = _normalize_date(data['target_collection_date']) or None
        updated['target_collection_date'] = str(rec.target_collection_date) if rec.target_collection_date else None
    if 'notes' in data:
        rec.notes = (data['notes'] or '').strip()
        updated['notes'] = rec.notes
    if not updated:
        return err('没有可更新的字段')
    # Use update() to avoid triggering full save/recompute
    ARRecord.objects.filter(pk=pk).update(**{k: getattr(rec, k) for k in updated})
    return ok(updated)
