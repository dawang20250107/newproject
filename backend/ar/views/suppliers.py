"""供应商池（supplier pool）业务域视图：供应商列表/详情/检索，含预付余额聚合。
共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

# ══════════════════════════════════════════════════════════════════════════════
# Supplier pool (供应商池)
# ══════════════════════════════════════════════════════════════════════════════

def _supplier_prepaid_agg(s):
    """Return prepaid balance/count for a supplier (one DB query)."""
    qs = AdvanceRecord.objects.filter(
        direction='预付', balance_amount__gt=0, counterparty__iexact=s.name)
    if s.project_id:
        qs = qs.filter(project_id=s.project_id)
    elif s.delivery_dept:
        qs = qs.filter(delivery_dept=s.delivery_dept)
    agg = qs.aggregate(total=Sum('balance_amount'), cnt=Count('id'))
    return str(agg['total'] or Decimal('0')), agg['cnt'] or 0


@csrf_exempt
@pk_required()
def suppliers(request):
    """GET = list, POST = create."""
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied

    if request.method == 'GET':
        qs = Supplier.objects.select_related('project', 'created_by')
        qs = _ar_dept_filter(qs, request)
        stype = request.GET.get('type', '').strip()
        if stype in ('private', 'public'):
            qs = qs.filter(supplier_type=stype)
        project_id = request.GET.get('project_id', '').strip()
        if project_id:
            qs = qs.filter(project_id=int(project_id))
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(contact__icontains=q) | Q(notes__icontains=q))
        items = []
        for s in qs:
            d = s.to_dict()
            d['prepaid_balance'], d['prepaid_count'] = _supplier_prepaid_agg(s)
            items.append(d)
        return ok({'items': items, 'total': len(items)})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        name = (data.get('name') or '').strip()
        if not name:
            return err('供应商名称不能为空')
        stype = data.get('supplier_type', 'public')
        if stype not in ('private', 'public'):
            return err('类型无效')
        project = None
        delivery_dept = (data.get('delivery_dept') or '').strip()
        if stype == 'private':
            pid = data.get('project_id')
            if not pid:
                return err('私有供应商必须关联项目')
            try:
                project = ARProject.objects.get(pk=int(pid))
            except (ARProject.DoesNotExist, ValueError, TypeError):
                return err('项目不存在', 404)
            dep = _dept_denied(request, project.delivery_dept)
            if dep:
                return dep
            delivery_dept = project.delivery_dept
        else:
            if not delivery_dept:
                return err('公共供应商必须指定交付部门')
            if delivery_dept not in VALID_DEPARTMENTS:
                return err('无效部门')
            dep = _dept_denied(request, delivery_dept)
            if dep:
                return dep
        s = Supplier.objects.create(
            name=name, supplier_type=stype, project=project,
            delivery_dept=delivery_dept,
            contact=(data.get('contact') or '').strip(),
            notes=(data.get('notes') or '').strip(),
            created_by_id=request.pk_uid)
        return ok(s.to_dict())

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def supplier_detail(request, pk):
    denied = _page_denied(request, 'ar_advance')
    if denied:
        return denied
    try:
        s = Supplier.objects.select_related('project', 'created_by').get(pk=pk)
    except Supplier.DoesNotExist:
        return err('供应商不存在', 404)
    if request.pk_role != 'super_admin' and s.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)

    if request.method == 'GET':
        d = s.to_dict()
        d['prepaid_balance'], d['prepaid_count'] = _supplier_prepaid_agg(s)
        adv_qs = AdvanceRecord.objects.filter(
            direction='预付', balance_amount__gt=0, counterparty__iexact=s.name)
        if s.project_id:
            adv_qs = adv_qs.filter(project_id=s.project_id)
        elif s.delivery_dept:
            adv_qs = adv_qs.filter(delivery_dept=s.delivery_dept)
        d['prepaid_advances'] = [a.to_dict() for a in adv_qs.order_by('-occur_date')]
        return ok(d)

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        if 'name' in data:
            v = (data['name'] or '').strip()
            if not v:
                return err('供应商名称不能为空')
            s.name = v
        if 'contact' in data:
            s.contact = (data['contact'] or '').strip()
        if 'notes' in data:
            s.notes = (data['notes'] or '').strip()
        if s.supplier_type == 'public' and 'delivery_dept' in data:
            nd = (data['delivery_dept'] or '').strip()
            if nd and nd in VALID_DEPARTMENTS:
                dep = _dept_denied(request, nd)
                if dep:
                    return dep
                s.delivery_dept = nd
        s.save()
        return ok(s.to_dict())

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        s.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def supplier_search(request):
    """Fuzzy-search suppliers by payee name for PaymentModal matching.
    Returns matched suppliers with prepaid balance and open advances (up to 5 each).
    """
    if request.method != 'GET':
        return err('Method not allowed', 405)
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return ok({'items': []})
    dept = request.GET.get('dept', '').strip()
    qs = Supplier.objects.select_related('project')
    if request.pk_role != 'super_admin':
        allowed = list(request.pk_depts or [])
        if not allowed:
            return ok({'items': []})
        if dept and dept in allowed:
            qs = qs.filter(delivery_dept=dept)
        else:
            qs = qs.filter(delivery_dept__in=allowed)
    elif dept:
        qs = qs.filter(delivery_dept=dept)
    qs = qs.filter(name__icontains=q)[:10]
    items = []
    for s in qs:
        d = s.to_dict()
        adv_qs = AdvanceRecord.objects.filter(
            direction='预付', balance_amount__gt=0, counterparty__iexact=s.name)
        if s.project_id:
            adv_qs = adv_qs.filter(project_id=s.project_id)
        elif s.delivery_dept:
            adv_qs = adv_qs.filter(delivery_dept=s.delivery_dept)
        agg = adv_qs.aggregate(total=Sum('balance_amount'), cnt=Count('id'))
        d['prepaid_balance'] = str(agg['total'] or Decimal('0'))
        d['prepaid_count'] = agg['cnt'] or 0
        d['prepaid_advances'] = [
            {'id': a.id, 'advance_amount': str(a.advance_amount),
             'balance_amount': str(a.balance_amount),
             'occur_date': str(a.occur_date) if a.occur_date else None,
             'notes': a.notes}
            for a in adv_qs.order_by('-occur_date')[:5]
        ]
        items.append(d)
    return ok({'items': items})
