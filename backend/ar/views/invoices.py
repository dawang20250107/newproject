"""合并开票批次（invoice batches）业务域：按 invoice_batch_no 分组汇总 + 批量开票/付款及撤销 + 批量打标。共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

# ──────────────────────────────────────────────────────────────────────────────
# 合并开票批次 — 按 invoice_batch_no 分组汇总 + 批量打标
# ──────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def ar_invoice_batches(request):
    """GET /records/invoice-batches  —  列出所有已标记开票批次及其汇总。

    每个 invoice_batch_no 非空的批次返回：
      batch_no, count, estimated, invoiced, outstanding, record_ids, dept_names
    支持 dept / year / month 维度筛选，以及 q（简称/合同名/编号模糊匹配）。
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)

    today = datetime.date.today()
    qs = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
    qs = _apply_record_filters(qs, request)
    qs = _apply_conditions(qs, request, today)
    # 只看有批次号的记录
    qs = qs.exclude(invoice_batch_no='')

    # 分组聚合（避免 payments JOIN 行扇出：先算记录级，再单独算已收）
    base = (qs.values('invoice_batch_no').annotate(
        count=Count('id'),
        estimated=Sum('estimated_amount'),
        invoiced=Sum('actual_invoice_amount'),
        outstanding=Sum('outstanding_amount', filter=Q(outstanding_amount__gt=0)),
    ).order_by('invoice_batch_no'))

    collected_map = {
        g['invoice_batch_no']: (g['s'] or 0)
        for g in qs.values('invoice_batch_no').annotate(s=Sum('payments__amount'))
    }

    # 每批次的明细 record_ids、部门与客户列表（小数据量下内存聚合比子查询清晰）
    id_dept_map = defaultdict(lambda: {'ids': [], 'depts': set(), 'customers': set()})
    for r in qs.values('id', 'invoice_batch_no', 'delivery_dept', 'project__customer_name'):
        m = id_dept_map[r['invoice_batch_no']]
        m['ids'].append(r['id'])
        m['depts'].add(r['delivery_dept'])
        if r['project__customer_name']:
            m['customers'].add(r['project__customer_name'])

    rows = []
    for g in base:
        bn = g['invoice_batch_no']
        meta = id_dept_map[bn]
        custs = sorted(meta['customers'])
        rows.append({
            'batch_no': bn,
            'count': g['count'] or 0,
            'estimated': str(g['estimated'] or 0),
            'invoiced': str(g['invoiced'] or 0),
            'outstanding': str(g['outstanding'] or 0),
            'collected': str(collected_map.get(bn, 0)),
            'record_ids': sorted(meta['ids']),
            'dept_names': sorted(meta['depts']),
            'customers': custs[:3] + (['…'] if len(custs) > 3 else []),
        })

    return ok({'batches': rows, 'total': len(rows)})


def _batch_members_qs(request, batch_no):
    """某开票批次在当前用户作用域内的成员记录（含项目信息，按运作日期排序）。"""
    return (_ar_dept_filter(ARRecord.objects.select_related('project'), request,
                            shared_field='project__is_shared')
            .filter(invoice_batch_no=batch_no)
            .order_by('operation_date', 'id'))


def _batch_member_dict(rec):
    billable = (rec.estimated_amount or Decimal('0')) + (rec.account_diff_adjustment or Decimal('0'))
    collected = rec.payments.aggregate(s=Sum('amount'))['s'] or Decimal('0')
    adjustments = [{'reason': a.reason, 'amount': str(a.amount)} for a in rec.adjustments.all()]
    # 税额体现：已开票的取记录税额（全额模式自动算/差额模式手填）；
    # 未开票的按项目税率给预估（全额模式），差额模式无法预估标 None
    rate = rec.project.tax_rate or Decimal('0')
    if rec.actual_invoice_amount is not None:
        tax_show = rec.tax_amount
    elif rec.project.invoice_mode == '全额' and rate:
        tax_show = (billable / (1 + rate) * rate).quantize(Decimal('0.01'))
    else:
        tax_show = None
    return {
        'adjustments': adjustments,
        'tax_rate': str(rate),
        'invoice_mode': rec.project.invoice_mode,
        'tax_amount': str(tax_show) if tax_show is not None else None,
        'id': rec.id,
        'short_name': rec.project.short_name,
        'customer_name': rec.project.customer_name,
        'delivery_dept': rec.delivery_dept,
        'operation_date': str(rec.operation_date) if rec.operation_date else None,
        'estimated': str(rec.estimated_amount or 0),
        'diff': str(rec.account_diff_adjustment or 0),
        'billable': str(billable),
        'invoiced': str(rec.actual_invoice_amount) if rec.actual_invoice_amount is not None else None,
        'invoice_room': str(billable - (rec.actual_invoice_amount or Decimal('0'))),
        'invoice_date': str(rec.invoice_date) if rec.invoice_date else None,
        'collected': str(collected),
        'outstanding': str(rec.outstanding_amount or 0),
    }


@csrf_exempt
@pk_required()
def ar_invoice_batch_detail(request, batch_no):
    """GET /records/invoice-batches/<batch_no> — 批次明细：成员逐条 + 汇总。
    应开口径 = 上账金额 + 账实差额调整（差额已按业务要求落在具体记录上）。"""
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)
    members = [_batch_member_dict(r) for r in _batch_members_qs(request, batch_no)]
    if not members:
        return err('批次不存在或无权访问', 404)
    # 批次回款事件：成员回款中备注带本批次标记的，按(日期+备注)聚合还原为
    # 「某天的一次批次回款」，支持整次撤销
    member_ids = [m['id'] for m in members]
    tag = f'批次回款[{batch_no}]'
    events = {}
    for p in (ARPayment.objects.filter(ar_record_id__in=member_ids,
                                       notes__startswith=tag)
              .order_by('payment_date', 'id')):
        key = (str(p.payment_date), p.notes)
        ev = events.setdefault(key, {'payment_date': str(p.payment_date),
                                     'notes': p.notes, 'total': Decimal('0'),
                                     'count': 0, 'payment_ids': []})
        ev['total'] += p.amount or Decimal('0')
        ev['count'] += 1
        ev['payment_ids'].append(p.id)
    collections = [{**e, 'total': str(e['total'])} for e in events.values()]
    invoice_events = [e.to_dict() for e in
                      BatchInvoiceEvent.objects.filter(batch_no=batch_no)]
    s = lambda k: sum(Decimal(m[k]) for m in members if m[k] is not None)  # noqa: E731
    return ok({
        'batch_no': batch_no,
        'members': members,
        'collections': collections,
        'invoice_events': invoice_events,
        'summary': {
            'count': len(members),
            'estimated': str(s('estimated')),
            'diff': str(s('diff')),
            'billable': str(s('billable')),
            'invoiced': str(s('invoiced')),
            'tax': str(s('tax_amount')),
            'collected': str(s('collected')),
            'outstanding': str(s('outstanding')),
            'invoice_room': str(s('invoice_room')),
            'pending_invoice': sum(1 for m in members if m['invoiced'] is None),
        },
    })


@csrf_exempt
@pk_required()
def ar_invoice_batch_invoice(request, batch_no):
    """POST /records/invoice-batches/<batch_no>/invoice — 批次开票（金额级分批）。

    body: { invoice_date(必填), amount(必填,价税合计), tax_amount(选填,差额模式手填),
            notes(选填) }
    与批次回款同构：每次开票一个事件，金额按运作日期先进先出分摊到成员的
    「可开余额」（上账+差额−已开）。可多次开票，累计不超过批次可开总额即放行。
    税额：全额模式记录随分摊按项目税率自动重算；差额模式记录按分摊占比
    分配手填税额。每个事件可整次撤销。
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _write_denied(request)
    if denied:
        return denied
    data = _parse_body(request)
    inv_date = _normalize_date(data.get('invoice_date'))
    if not inv_date:
        return err('开票日期无效（格式 2026-01-15）')
    amount = _dec(data.get('amount') or data.get('invoice_total') or 0)
    if amount <= 0:
        return err('开票金额必须大于0（价税合计）')
    tax_raw = data.get('tax_amount')
    manual_tax = _dec(tax_raw) if tax_raw not in (None, '') else None
    if manual_tax is not None and (manual_tax < 0 or manual_tax >= amount):
        return err('税额无效：须 ≥0 且小于开票金额')

    from paikuan.models import PaikuanUser
    user = PaikuanUser.objects.filter(id=request.pk_uid).first()

    allocations = []
    try:
        with transaction.atomic():
            members = list(_batch_members_qs(request, batch_no).select_for_update())
            if not members:
                return err('批次不存在或无权访问', 404)

            def _room(r):
                billable = ((r.estimated_amount or Decimal('0'))
                            + (r.account_diff_adjustment or Decimal('0')))
                return billable - (r.actual_invoice_amount or Decimal('0'))

            open_recs = [r for r in members if _room(r) > 0]
            total_room = sum(_room(r) for r in open_recs)
            if total_room <= 0:
                return err('该批次可开余额已用尽（累计开票已达 上账+差额 合计）')
            if amount > total_room:
                return err(f'开票金额 {amount} 超过批次可开余额 {total_room}'
                           f'（上账+差额合计 − 累计已开）。'
                           f'如金额确实更大，请先在具体记录上追加「差额调整」')

            # 差额模式记录的手填税额按分摊占比分配；先算分摊再分税
            remaining = amount
            plan = []
            for r in open_recs:
                if remaining <= 0:
                    break
                alloc = min(remaining, _room(r))
                plan.append((r, alloc))
                remaining -= alloc
            diff_alloc_total = sum(a for r, a in plan if r.project.invoice_mode == '差额')
            for r, alloc in plan:
                r.actual_invoice_amount = (r.actual_invoice_amount or Decimal('0')) + alloc
                r.invoice_date = inv_date
                if (manual_tax is not None and r.project.invoice_mode == '差额'
                        and diff_alloc_total > 0):
                    share = (manual_tax * alloc / diff_alloc_total).quantize(Decimal('0.01'))
                    r.tax_amount = (r.tax_amount or Decimal('0')) + share
                r.save()   # 全额模式税额由 save() 按税率自动重算
                allocations.append({'record_id': r.id,
                                    'short_name': r.project.short_name,
                                    'operation_date': str(r.operation_date) if r.operation_date else None,
                                    'amount': str(alloc),
                                    'invoiced_after': str(r.actual_invoice_amount)})
            ev = BatchInvoiceEvent.objects.create(
                batch_no=batch_no, invoice_date=inv_date, amount=amount,
                tax_amount=manual_tax, notes=(data.get('notes') or '').strip()[:200],
                allocations=[{'record_id': a['record_id'], 'amount': a['amount']}
                             for a in allocations],
                created_by=user)
    except ValidationError as e:
        return err(str(e.message if hasattr(e, 'message') else e), 400)

    left = total_room - amount
    return ok({
        'event': ev.to_dict(), 'allocations': allocations,
        'message': (f'批次「{batch_no}」开票 {amount} 已按先进先出分摊到 '
                    f'{len(allocations)} 条记录' +
                    (f'，批次剩余可开 {left}' if left > 0 else '，批次已开满')),
    })


@csrf_exempt
@pk_required()
def ar_invoice_batch_invoice_undo(request, batch_no):
    """POST /records/invoice-batches/<batch_no>/invoice-undo — 整次撤销开票事件。

    body: { event_id }。按事件保存的分摊明细逐条回退各记录的开票金额
    （回退后为0则清空开票金额与日期），全额模式税额自动重算，
    差额模式按事件手填税额比例回退。事务整体执行。
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _write_denied(request)
    if denied:
        return denied
    data = _parse_body(request)
    try:
        ev = BatchInvoiceEvent.objects.get(pk=int(data.get('event_id') or 0),
                                           batch_no=batch_no)
    except (BatchInvoiceEvent.DoesNotExist, ValueError, TypeError):
        return err('开票事件不存在（可能已撤销）', 404)

    member_ids = set(_batch_members_qs(request, batch_no).values_list('id', flat=True))
    if not member_ids:
        return err('批次不存在或无权访问', 404)
    diff_total = sum(Decimal(a['amount']) for a in ev.allocations or [])
    try:
        with transaction.atomic():
            for a in (ev.allocations or []):
                rid, amt = a['record_id'], Decimal(a['amount'])
                if rid not in member_ids:
                    return err(f'记录 #{rid} 不在当前批次作用域内，无法撤销', 403)
                r = ARRecord.objects.select_related('project').select_for_update().get(pk=rid)
                cur = r.actual_invoice_amount or Decimal('0')
                if cur < amt:
                    return err(f'记录 #{rid} 当前开票额 {cur} 小于本事件分摊 {amt}，'
                               f'（可能已被人工修改）请先核对该记录')
                new_val = cur - amt
                if ev.tax_amount is not None and r.project.invoice_mode == '差额' and diff_total > 0:
                    share = (ev.tax_amount * amt / diff_total).quantize(Decimal('0.01'))
                    r.tax_amount = max(Decimal('0'), (r.tax_amount or Decimal('0')) - share)
                if new_val <= 0:
                    r.actual_invoice_amount = None
                    r.invoice_date = None
                    if r.project.invoice_mode == '全额':
                        r.tax_amount = None
                else:
                    r.actual_invoice_amount = new_val
                r.save()
            ev_id = ev.pk
            ev.delete()
    except ARRecord.DoesNotExist:
        return err('分摊涉及的记录已不存在，无法撤销', 404)
    except ValidationError as e:
        return err(str(e.message if hasattr(e, 'message') else e), 400)
    return ok({'undone': ev_id,
               'message': f'已撤销 {ev.invoice_date} 的开票 {ev.amount}，各记录开票额已回退'})


@csrf_exempt
@pk_required()
def ar_invoice_batch_payment(request, batch_no):
    """POST /records/invoice-batches/<batch_no>/payment — 批次回款自动分摊。

    body: { amount(必填), payment_date(必填), notes(选填) }
    一张发票（批次）到一笔钱：按运作日期先进先出，逐条冲减成员未收余额，
    自动生成各记录的回款行（备注带批次号，可追溯）。支持多次回款，
    每次都从当前仍有未收的成员继续分摊。金额超过批次未收合计 → 拒绝并
    提示超出部分走「预收款」。
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _action_denied(request, 'ar_collect')
    if denied:
        return denied
    denied = _ar_field_denied(request, 'r_payments')
    if denied:
        return denied
    data = _parse_body(request)
    amount = _dec(data.get('amount', 0))
    if amount <= 0:
        return err('回款金额必须大于0')
    pay_date = _normalize_date(data.get('payment_date'))
    if not pay_date:
        return err('回款日期无效（格式 2026-01-20）')
    user_notes = (data.get('notes') or '').strip()

    with transaction.atomic():
        members = list(_batch_members_qs(request, batch_no).select_for_update())
        if not members:
            return err('批次不存在或无权访问', 404)
        open_recs = [r for r in members if (r.outstanding_amount or Decimal('0')) > 0]
        total_outstanding = sum(r.outstanding_amount for r in open_recs)
        if not open_recs:
            return err('该批次已全部回款结清，无未收余额可分摊')
        if amount > total_outstanding:
            return err(f'回款金额 {amount} 超过批次未收合计 {total_outstanding}。'
                       f'请按 {total_outstanding} 录入本批次回款，'
                       f'超出的 {amount - total_outstanding} 元到「预收预付」录入为该客户预收款')

        remaining = amount
        allocations = []
        note = f'批次回款[{batch_no}]' + (f' {user_notes}' if user_notes else '')
        for r in open_recs:
            if remaining <= 0:
                break
            alloc = min(remaining, r.outstanding_amount)
            last = r.payments.order_by('-payment_no').first()
            ARPayment.objects.create(
                ar_record=r, payment_no=(last.payment_no + 1) if last else 1,
                amount=alloc, payment_date=pay_date, notes=note)
            r.refresh_from_db()
            allocations.append({
                'record_id': r.id, 'short_name': r.project.short_name,
                'operation_date': str(r.operation_date) if r.operation_date else None,
                'allocated': str(alloc), 'outstanding_after': str(r.outstanding_amount),
            })
            remaining -= alloc

    settled = sum(1 for a in allocations if Decimal(a['outstanding_after']) <= 0)
    return ok({
        'batch_no': batch_no, 'amount': str(amount), 'allocations': allocations,
        'message': (f'批次「{batch_no}」回款 {amount} 已按运作日期先进先出分摊到 '
                    f'{len(allocations)} 条记录（{settled} 条就此结清）'),
    })


def _gen_batch_no(qs):
    """自动生成可读开票批次号：{客户简称}-{YYMMDD}-{序号}。

    人脑不该发明编码——号段以所选记录的客户为前缀（同客户取其名，多客户记
    「多户」），日期+当日序号保证唯一，看到号就知道是谁、哪天合并的。"""
    names = set()
    for r in qs.select_related('project')[:200]:
        n = (r.project.customer_name or r.project.short_name or '').strip()
        if n:
            names.add(n)
    base = (list(names)[0][:8] if len(names) == 1 else '多户') or '开票'
    prefix = f'{base}-{datetime.date.today().strftime("%y%m%d")}'
    seq = ARRecord.objects.filter(invoice_batch_no__startswith=prefix)\
        .values('invoice_batch_no').distinct().count() + 1
    return f'{prefix}-{seq:02d}'


@csrf_exempt
@pk_required()
def ar_invoice_batch_payment_undo(request, batch_no):
    """POST /records/invoice-batches/<batch_no>/payment-undo — 整次撤销批次回款。

    body: { payment_ids: [int,...] }（来自批次明细 collections 的一次回款事件）
    校验每笔都属于本批次成员且带本批次回款标记，事务内整体删除，
    各记录未收余额随信号恢复——错一笔即整体拒绝，不留半套状态。
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _action_denied(request, 'ar_collect')
    if denied:
        return denied
    data = _parse_body(request)
    ids = data.get('payment_ids') or []
    if not isinstance(ids, list) or not ids:
        return err('请提供要撤销的回款 payment_ids')
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        return err('payment_ids 必须为整数列表')

    member_ids = list(_batch_members_qs(request, batch_no).values_list('id', flat=True))
    if not member_ids:
        return err('批次不存在或无权访问', 404)
    tag = f'批次回款[{batch_no}]'
    pays = list(ARPayment.objects.filter(pk__in=ids))
    if len(pays) != len(set(ids)):
        return err('部分回款记录不存在（可能已被撤销）', 404)
    for p in pays:
        if p.ar_record_id not in member_ids:
            return err(f'回款 #{p.id} 不属于批次「{batch_no}」的成员记录，已拒绝')
        if not (p.notes or '').startswith(tag):
            return err(f'回款 #{p.id} 不是本批次的批次回款（{p.notes or "无标记"}），'
                       f'请到该应收记录上单独处理')
        if p.source == '预收抵扣':
            return err(f'回款 #{p.id} 为预收抵扣，请走「撤销核销」')
    total = sum(p.amount or Decimal('0') for p in pays)
    with transaction.atomic():
        ARPayment.objects.filter(pk__in=ids).delete()
    return ok({'undone': len(pays), 'total': str(total),
               'message': f'已撤销该次批次回款：{len(pays)} 笔合计 {total}，各记录未收已恢复'})


@csrf_exempt
@pk_required()
def ar_records_batch_assign(request):
    """POST /records/batch-assign  —  批量设置 invoice_batch_no。

    Body: { "ids": [1,2,3], "invoice_batch_no": "..." } 或 { "ids": [...], "auto": true }
    auto=true 时系统自动生成可读批次号（客户简称-日期-序号），无需人为编码。
    ids 为空 + all=true 时：对当前筛选全集打标（与 bulk-delete 对齐，但限 5000 条）。
    invoice_batch_no 传空字符串且非 auto 则清空批次（取消合并）。
    """
    denied = _page_denied(request, 'ar_records')
    if denied:
        return denied
    denied = _write_denied(request)
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)

    data = _parse_body(request)
    batch_no = (data.get('invoice_batch_no') or '').strip()[:50]
    auto = data.get('auto') in (True, 'true', '1')
    all_flag = data.get('all') in (True, 'true', '1')
    ids = data.get('ids')

    if all_flag:
        today = datetime.date.today()
        qs = _ar_dept_filter(ARRecord.objects.all(), request, shared_field='project__is_shared')
        qs = _apply_record_filters(qs, request)
        qs = _apply_record_state_filters(qs, request, today)
        qs = _apply_conditions(qs, request, today)
        if qs.count() > 5000:
            return err('选中记录超过5000条，请缩小筛选范围后再批量操作')
    else:
        if not ids or not isinstance(ids, list):
            return err('请传入 ids 数组或 all=true')
        # 权限：只允许操作自己部门的记录
        qs = ARRecord.objects.filter(pk__in=[int(i) for i in ids])
        if request.pk_role != 'super_admin':
            qs = qs.filter(delivery_dept__in=request.pk_depts)

    if auto and not batch_no:
        batch_no = _gen_batch_no(qs)
    updated = qs.update(invoice_batch_no=batch_no)

    action = f'设置批次号为「{batch_no}」' if batch_no else '清空批次号'
    return ok({'updated': updated, 'invoice_batch_no': batch_no,
               'message': f'{action}，共更新 {updated} 条记录'})




# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
