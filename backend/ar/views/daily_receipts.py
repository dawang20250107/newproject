"""日常收款（daily receipts）业务域：一般性现金流入台账（项目收款/预付退款/自定义来源）。
全额计入现金流与资金池（见 pool.py / cashflow.py 对 DailyReceipt 的聚合）。共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

_PAGE = 'ar_daily_receipts'


def _visible_depts(request):
    """可见事业部 = 授权部门（超管=全部）∩ 全局激活范围(?depts)。与资金池口径一致。"""
    if request.pk_role == 'super_admin':
        allowed = list(DEPARTMENTS)
    else:
        allowed = [d for d in (request.pk_depts or []) if d in VALID_DEPARTMENTS]
    raw = (request.GET.get('depts') or '').strip()
    if raw:
        requested = [d for d in raw.split(',') if d.strip()]
        active = [d for d in allowed if d in requested]
        if active:
            return active
    return allowed


def _clean_payload(request, data):
    """校验并规整收款表单，返回 (fields_dict, project_obj, err_response)。"""
    dept = (data.get('delivery_dept') or '').strip()
    if dept not in VALID_DEPARTMENTS:
        return None, None, err('无效的事业部')
    # 非超管只能录本部门
    if request.pk_role != 'super_admin' and dept not in (request.pk_depts or []):
        return None, None, err('只能录入本部门的收款', 403, 403)
    rdate = _normalize_date(data.get('receipt_date'))
    if not rdate:
        return None, None, err('收款日期必填（YYYY-MM-DD）')
    try:
        rdate_d = datetime.date.fromisoformat(str(rdate)[:10])
    except (ValueError, TypeError):
        return None, None, err('收款日期格式错误')
    if rdate_d > timezone.localdate():
        return None, None, err('收款日期不能晚于今天')
    try:
        amount = Decimal(str(data.get('amount') or 0))
    except (InvalidOperation, ValueError):
        return None, None, err('金额格式错误')
    if amount <= 0:
        return None, None, err('收款金额必须大于 0')
    source = (data.get('source') or '').strip()
    if not source:
        return None, None, err('收款来源必填')
    project = None
    pid = data.get('project_id')
    if pid:
        project = ARProject.objects.filter(id=pid).first()
        if not project:
            return None, None, err('所选项目不存在')
    fields = {
        'delivery_dept': dept, 'receipt_date': rdate_d, 'amount': amount,
        'source': source[:40], 'method': (data.get('method') or '').strip()[:20],
        'account': (data.get('account') or '').strip()[:50],
        'payer': (data.get('payer') or '').strip()[:100],
        'notes': (data.get('notes') or '').strip(),
    }
    return fields, project, None


@csrf_exempt
@pk_required()
def daily_receipts(request):
    """GET 列表（按事业部/来源/方式/日期区间/项目筛选，带合计）；POST 新增一笔收款。"""
    denied = _page_denied(request, _PAGE)
    if denied:
        return denied

    if request.method == 'GET':
        depts = _visible_depts(request)
        qs = DailyReceipt.objects.filter(delivery_dept__in=depts).select_related('project', 'created_by')
        src = (request.GET.get('source') or '').strip()
        if src:
            qs = qs.filter(source=src)
        method = (request.GET.get('method') or '').strip()
        if method:
            qs = qs.filter(method=method)
        pid = (request.GET.get('project_id') or '').strip()
        if pid.isdigit():
            qs = qs.filter(project_id=int(pid))
        s = _normalize_date(request.GET.get('start_date'))
        e = _normalize_date(request.GET.get('end_date'))
        if s:
            qs = qs.filter(receipt_date__gte=s)
        if e:
            qs = qs.filter(receipt_date__lte=e)
        kw = (request.GET.get('q') or '').strip()
        if kw:
            qs = qs.filter(Q(payer__icontains=kw) | Q(notes__icontains=kw)
                           | Q(source__icontains=kw) | Q(project__short_name__icontains=kw)
                           | Q(project__customer_name__icontains=kw))
        total = _dec(qs.aggregate(s=Sum('amount'))['s'])
        by_method = {r['method'] or '未填': str(_dec(r['s'])) for r in
                     qs.values('method').annotate(s=Sum('amount'))}
        by_source = {r['source']: str(_dec(r['s'])) for r in
                     qs.values('source').annotate(s=Sum('amount'))}
        items = [r.to_dict() for r in qs[:1000]]
        return ok({'items': items, 'count': qs.count(), 'total': str(total),
                   'by_method': by_method, 'by_source': by_source,
                   'source_presets': DailyReceipt.SOURCE_PRESETS,
                   'method_presets': DailyReceipt.METHOD_PRESETS,
                   'departments': _visible_depts(request)})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        fields, project, bad = _clean_payload(request, data)
        if bad:
            return bad
        rec = DailyReceipt.objects.create(project=project, created_by=request.pk_user, **fields)
        return ok(rec.to_dict())

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def daily_receipt_detail(request, pk):
    """PUT 编辑 / DELETE 删除一笔收款。"""
    denied = _page_denied(request, _PAGE)
    if denied:
        return denied
    try:
        rec = DailyReceipt.objects.get(pk=pk)
    except DailyReceipt.DoesNotExist:
        return err('收款记录不存在', 404)
    if request.pk_role != 'super_admin' and rec.delivery_dept not in (request.pk_depts or []):
        return err('无权操作其他部门的收款', 403, 403)

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        fields, project, bad = _clean_payload(request, data)
        if bad:
            return bad
        for k, v in fields.items():
            setattr(rec, k, v)
        rec.project = project
        rec.save()
        return ok(rec.to_dict())

    if request.method == 'DELETE':
        denied = _write_denied(request)
        if denied:
            return denied
        rec.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def daily_receipts_bulk_delete(request):
    """POST {ids:[...]} → 批量删除收款（仅本人可见部门；超管不限）。"""
    denied = _page_denied(request, _PAGE)
    if denied:
        return denied
    denied = _write_denied(request)
    if denied:
        return denied
    ids = _parse_body(request).get('ids') or []
    if not isinstance(ids, list) or not ids:
        return err('请选择要删除的记录')
    qs = DailyReceipt.objects.filter(id__in=ids)
    if request.pk_role != 'super_admin':
        qs = qs.filter(delivery_dept__in=(request.pk_depts or []))
    n = qs.count()
    qs.delete()
    return ok({'deleted': n})


# 再导出本域全部公开名，使 `from ar.views import daily_receipts` 等引用可用。
__all__ = [n for n in dir() if not n.startswith('__')]
