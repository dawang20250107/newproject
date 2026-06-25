"""行动项（action items）业务域视图：P4 决策闭环——列表/创建/详情、从今日信号生成。
共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

# ─────────────────────────────────────────────────────────────────────────────
# P4 决策闭环 — 行动项 (Action Items)
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def ar_actions(request):
    """GET: list action items with counts; POST: create one."""
    # dept-scope filter helper（bu='' 为全局事项，对所有人可见；
    # 无授权部门的非超管只看全局事项，杜绝「空部门=看全部」越权）
    def _scope_qs(qs):
        if request.pk_role == 'super_admin':
            return qs
        return qs.filter(Q(bu='') | Q(bu__in=request.pk_depts or []))

    if request.method == 'GET':
        qs = _scope_qs(ActionItem.objects.all())
        status_f = request.GET.get('status')
        bu_f = request.GET.get('bu')
        priority_f = request.GET.get('priority')
        if status_f:
            qs = qs.filter(status=status_f)
        if bu_f:
            qs = qs.filter(bu=bu_f)
        if priority_f:
            qs = qs.filter(priority=priority_f)

        items = [i.to_dict() for i in qs.select_related('created_by', 'resolved_by')[:300]]

        all_qs = _scope_qs(ActionItem.objects.all())
        counts = {s: all_qs.filter(status=s).count()
                  for s in ('open', 'in_progress', 'done', 'dismissed')}
        return ok({'items': items, 'counts': counts})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        title = (data.get('title') or '').strip()
        if not title:
            return err('标题不能为空')
        item = ActionItem(
            title=title,
            description=(data.get('description') or '').strip(),
            bu=(data.get('bu') or '').strip(),
            category=(data.get('category') or '').strip(),
            priority=data.get('priority', 'medium'),
            assignee=(data.get('assignee') or '').strip(),
            source_signal=data.get('source_signal') or {},
        )
        if data.get('due_date'):
            item.due_date = _normalize_date(data['due_date'])
        if hasattr(request, 'pk_user') and request.pk_user:
            item.created_by = request.pk_user
        item.save()
        return ok(item.to_dict())

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_action_detail(request, pk):
    """GET/PUT/DELETE single action item."""
    try:
        item = ActionItem.objects.select_related('created_by', 'resolved_by').get(pk=pk)
    except ActionItem.DoesNotExist:
        return err('行动项不存在', 404)

    # 与列表口径一致：bu='' 为全局事项；指定 bu 的事项仅本部门（或超管）可见可改
    if (request.pk_role != 'super_admin' and item.bu
            and item.bu not in (request.pk_depts or [])):
        return err('无权访问', 403, 403)

    if request.method == 'GET':
        return ok(item.to_dict())

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        if 'title' in data:
            t = (data['title'] or '').strip()
            if t:
                item.title = t
        if 'description' in data:
            item.description = (data['description'] or '').strip()
        if 'bu' in data:
            item.bu = (data['bu'] or '').strip()
        if 'priority' in data and data['priority'] in ('high', 'medium', 'low'):
            item.priority = data['priority']
        if 'assignee' in data:
            item.assignee = (data['assignee'] or '').strip()
        if 'due_date' in data:
            item.due_date = _normalize_date(data['due_date']) if data['due_date'] else None
        if 'status' in data:
            new_st = data['status']
            if new_st in ('open', 'in_progress', 'done', 'dismissed'):
                old_st = item.status
                item.status = new_st
                if new_st == 'done' and old_st != 'done':
                    item.resolved_at = datetime.datetime.now(datetime.timezone.utc)
                    if hasattr(request, 'pk_user') and request.pk_user:
                        item.resolved_by = request.pk_user
                elif new_st != 'done':
                    item.resolved_at = None
                    item.resolved_by = None
        item.save()
        return ok(item.to_dict())

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        item.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def ar_actions_from_signal(request):
    """POST: auto-create an action item from a today-signal dict.
    Deduplicates: if open/in_progress item exists with same category+bu, returns it.
    """
    if request.method != 'POST':
        return err('Method not allowed', 405)
    denied = _write_denied(request)
    if denied:
        return denied

    data = _parse_body(request)
    signal = data.get('signal') or {}
    category = (signal.get('type') or signal.get('category') or 'general').strip()
    bu = (signal.get('bu') or '').strip()

    # Deduplicate
    existing = ActionItem.objects.filter(
        category=category, bu=bu, status__in=['open', 'in_progress']
    ).first()
    if existing:
        return ok({'item': existing.to_dict(), 'created': False, 'msg': '已有同类待处理行动项'})

    priority_map = {
        'critical': 'high', 'overdue': 'high', 'cash_risk': 'high',
        'low_margin': 'medium', 'forecast': 'medium', 'baddebt': 'high',
    }
    level = signal.get('level') or signal.get('type') or ''
    priority = priority_map.get(level, 'medium')
    title = (signal.get('title') or signal.get('label') or '待处理事项').strip()

    item = ActionItem(
        title=title,
        description=(signal.get('desc') or signal.get('description') or '').strip(),
        bu=bu,
        category=category,
        priority=priority,
        source_signal=signal,
    )
    if hasattr(request, 'pk_user') and request.pk_user:
        item.created_by = request.pk_user
    item.save()
    return ok({'item': item.to_dict(), 'created': True})




# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
