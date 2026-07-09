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


def _clean_payload(request, data, rec=None):
    """校验并规整收款表单，返回 (fields_dict, project_obj, advance_obj, err_response)。
    rec：编辑时传入当前记录，用于把本笔原先占用的预付余额加回来做上限校验。"""
    dept = (data.get('delivery_dept') or '').strip()
    if dept not in VALID_DEPARTMENTS:
        return None, None, None, err('无效的事业部')
    # 非超管只能录本部门
    if request.pk_role != 'super_admin' and dept not in (request.pk_depts or []):
        return None, None, None, err('只能录入本部门的收款', 403, 403)
    rdate = _normalize_date(data.get('receipt_date'))
    if not rdate:
        return None, None, None, err('收款日期必填（YYYY-MM-DD）')
    try:
        rdate_d = datetime.date.fromisoformat(str(rdate)[:10])
    except (ValueError, TypeError):
        return None, None, None, err('收款日期格式错误')
    if rdate_d > timezone.localdate():
        return None, None, None, err('收款日期不能晚于今天')
    try:
        amount = Decimal(str(data.get('amount') or 0))
    except (InvalidOperation, ValueError):
        return None, None, None, err('金额格式错误')
    if amount <= 0:
        return None, None, None, err('收款金额必须大于 0')
    source = (data.get('source') or '').strip()
    if not source:
        return None, None, None, err('收款来源必填')
    project = None
    pid = data.get('project_id')
    if pid:
        project = ARProject.objects.filter(id=pid).first()
        if not project:
            return None, None, None, err('所选项目不存在')
    # 关联预付（仅「预付退款」）：退款回冲该预付未核销余额
    advance = None
    aid = data.get('advance_id')
    if aid:
        if source != DailyReceipt.SOURCE_REFUND:
            return None, None, None, err('仅「预付退款」可关联预付记录')
        advance = AdvanceRecord.objects.filter(id=aid, direction='预付').first()
        if not advance:
            return None, None, None, err('所选预付记录不存在或非预付方向', 404)
        if request.pk_role != 'super_admin' and advance.delivery_dept not in (request.pk_depts or []):
            return None, None, None, err('无权关联其他部门的预付', 403, 403)
        if advance.delivery_dept != dept:
            return None, None, None, err(
                f'预付所属部门「{advance.delivery_dept}」与收款部门「{dept}」不一致，不能关联')
        # 退款上限 = 该预付当前未核销余额 +（编辑时）本笔原先对同一预付的占用（将被替换）
        available = advance.balance_amount or Decimal('0')
        if rec is not None and rec.advance_record_id == advance.id:
            available += (rec.amount or Decimal('0'))
        if amount > available:
            return None, None, None, err(
                f'退款金额 {amount} 超过该预付未核销余额 {available}，请核对')
    fields = {
        'delivery_dept': dept, 'receipt_date': rdate_d, 'amount': amount,
        'source': source[:40], 'method': (data.get('method') or '').strip()[:20],
        'account': (data.get('account') or '').strip()[:50],
        'payer': (data.get('payer') or '').strip()[:100],
        'notes': (data.get('notes') or '').strip(),
    }
    return fields, project, advance, None


def _filtered_qs(request):
    """按可见部门 + 来源/方式/项目/日期/搜索过滤（列表与导出共用）。"""
    qs = DailyReceipt.objects.filter(delivery_dept__in=_visible_depts(request)).select_related('project')
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
    return qs


def _recompute_advances(ids):
    """退款关联变动后，重算相关预付的未核销余额（去重、忽略 None）。"""
    for aid in {i for i in ids if i}:
        adv = AdvanceRecord.objects.filter(pk=aid).first()
        if adv:
            adv.recompute_derived(save=True)


@csrf_exempt
@pk_required()
def daily_receipt_advances(request):
    """GET → 可关联的预付记录（direction=预付、未核销余额>0、本可见部门），供「预付退款」关联。
    独立于「预收预付」页面权限，按日常收款页面授权即可选。"""
    denied = _page_denied(request, _PAGE)
    if denied:
        return denied
    qs = (AdvanceRecord.objects.filter(direction='预付', balance_amount__gt=0,
                                       delivery_dept__in=_visible_depts(request))
          .select_related('project'))
    dept = (request.GET.get('dept') or '').strip()
    if dept:
        qs = qs.filter(delivery_dept=dept)
    kw = (request.GET.get('q') or '').strip()
    if kw:
        qs = qs.filter(Q(counterparty__icontains=kw) | Q(project__short_name__icontains=kw))
    items = [{
        'id': a.id, 'counterparty': a.counterparty,
        'occur_date': str(a.occur_date) if a.occur_date else '',
        'balance': str(a.balance_amount), 'delivery_dept': a.delivery_dept,
        'project_short_name': a.project.short_name if a.project_id else '',
    } for a in qs.order_by('-occur_date', '-id')[:50]]
    return ok({'items': items})


@csrf_exempt
@pk_required()
def daily_receipts_export(request):
    """GET → 导出当前筛选（或 ?ids= 选中）的收款为 Excel。"""
    denied = _page_denied(request, _PAGE)
    if denied:
        return denied
    qs = _filtered_qs(request)
    ids = (request.GET.get('ids') or '').strip()
    if ids:
        id_list = [int(x) for x in ids.split(',') if x.strip().isdigit()]
        qs = qs.filter(id__in=id_list)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '日常收款'
    headers = ['收款日期', '事业部', '收款来源', '关联项目', '收款方式', '收款账户',
               '付款方', '收款金额(元)', '摘要/备注']
    _header_row(ws, headers)
    for r in qs.order_by('-receipt_date', '-id'):
        proj = (r.project.short_name or r.project.customer_name) if r.project else ''
        ws.append([str(r.receipt_date), r.delivery_dept, r.source, proj, r.method,
                   r.account, r.payer, float(r.amount), r.notes])
    _style_export_ws(ws, money_headers=('收款金额(元)',))
    return _export_response(wb, f'日常收款_{timezone.localdate()}.xlsx')


@csrf_exempt
@pk_required()
def daily_receipts(request):
    """GET 列表（按事业部/来源/方式/日期区间/项目筛选，带合计）；POST 新增一笔收款。"""
    denied = _page_denied(request, _PAGE)
    if denied:
        return denied

    if request.method == 'GET':
        qs = _filtered_qs(request).select_related('created_by')
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
        fields, project, advance, bad = _clean_payload(request, data)
        if bad:
            return bad
        try:
            with transaction.atomic():
                if advance is not None:
                    # 锁预付行并在锁内复验上限：与并发核销/另一笔退款串行——
                    # 无锁时两笔各自校验通过、合计超额，CheckConstraint 只查写入列值拦不住
                    advance = AdvanceRecord.objects.select_for_update().get(pk=advance.pk)
                    if fields['amount'] > (advance.balance_amount or Decimal('0')):
                        return err(f'退款金额 {fields["amount"]} 超过该预付未核销余额 '
                                   f'{advance.balance_amount}，请核对')
                rec = DailyReceipt.objects.create(
                    project=project, advance_record=advance,
                    created_by=request.pk_user, **fields)
                if advance is not None:
                    advance.recompute_derived(save=True)   # 余额兜底校验（非负约束）在此
        except ValidationError as e:
            return err(str(getattr(e, 'message', e)))
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
        fields, project, advance, bad = _clean_payload(request, data, rec=rec)
        if bad:
            return bad
        old_adv_id = rec.advance_record_id
        try:
            with transaction.atomic():
                if advance is not None:
                    # 锁预付行并复验上限（本笔原先对同一预付的占用加回后比较），
                    # 与并发核销/退款串行，防合计超额
                    advance = AdvanceRecord.objects.select_for_update().get(pk=advance.pk)
                    available = advance.balance_amount or Decimal('0')
                    if old_adv_id == advance.id:
                        available += (rec.amount or Decimal('0'))
                    if fields['amount'] > available:
                        return err(f'退款金额 {fields["amount"]} 超过该预付未核销余额 '
                                   f'{available}，请核对')
                for k, v in fields.items():
                    setattr(rec, k, v)
                rec.project = project
                rec.advance_record = advance
                rec.save()
                # 先算新关联（含非负兜底），再回算旧关联（解绑/改绑后余额回升）
                new_id = advance.id if advance is not None else None
                _recompute_advances([new_id])
                if old_adv_id and old_adv_id != new_id:
                    _recompute_advances([old_adv_id])
        except ValidationError as e:
            return err(str(getattr(e, 'message', e)))
        return ok(rec.to_dict())

    if request.method == 'DELETE':
        denied = _write_denied(request)
        if denied:
            return denied
        adv_id = rec.advance_record_id
        with transaction.atomic():
            rec.delete()
            _recompute_advances([adv_id])   # 删退款 → 预付余额回升（同事务防 stale）
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
    adv_ids = list(qs.exclude(advance_record__isnull=True)
                   .values_list('advance_record_id', flat=True))
    with transaction.atomic():
        n = qs.count()
        qs.delete()
        _recompute_advances(adv_ids)    # 删退款 → 相关预付余额回升（同事务防 stale）
    return ok({'deleted': n})


# 再导出本域全部公开名，使 `from ar.views import daily_receipts` 等引用可用。
__all__ = [n for n in dir() if not n.startswith('__')]
