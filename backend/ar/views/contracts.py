"""合同管理（contracts）业务域视图：合同实体 + 多对多客户/项目关联。
共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

# ──────────────────────────────────────────────────────────────────────────────
# 合同管理 (contracts) — 合同实体 + 多对多客户/项目关联
# ──────────────────────────────────────────────────────────────────────────────

def _sync_contract_links(ct, data, request):
    """按请求体同步合同的客户(parties)与项目(projects)关联。
    仅当请求体包含对应键时才替换该侧关联（PATCH 语义，未传则不动）。"""
    # 客户：parties=[{customer_id, role, share}] 或 customer_ids=[id]
    if 'parties' in data or 'customer_ids' in data:
        ct.parties.all().delete()
        parties = data.get('parties')
        if parties is None:
            parties = [{'customer_id': cid, 'role': 'main'} for cid in (data.get('customer_ids') or [])]
        seen = set()
        for p in parties:
            cid = p.get('customer_id')
            if not cid or cid in seen or not Customer.objects.filter(pk=cid).exists():
                continue
            seen.add(cid)
            share = p.get('share')
            ContractParty.objects.create(
                contract=ct, customer_id=cid,
                role=p.get('role') if p.get('role') in ('main', 'sub') else 'main',
                share=_dec(share) if share not in (None, '') else None)
    # 项目：projects=[{project_id, is_primary}] 或 project_ids=[id]
    if 'projects' in data or 'project_ids' in data:
        ct.project_links.all().delete()
        projs = data.get('projects')
        if projs is None:
            projs = [{'project_id': pid, 'is_primary': True} for pid in (data.get('project_ids') or [])]
        seen = set()
        for pr in projs:
            pid = pr.get('project_id')
            if not pid or pid in seen:
                continue
            proj = ARProject.objects.filter(pk=pid).first()
            if not proj:
                continue
            # 只允许关联自己有权限部门的项目
            if request.pk_role != 'super_admin' and proj.delivery_dept not in request.pk_depts:
                continue
            seen.add(pid)
            ContractProject.objects.create(
                contract=ct, project=proj, is_primary=bool(pr.get('is_primary', True)))


@csrf_exempt
@pk_required()
def contracts(request):
    """GET  /ar/contracts  — 合同列表（按部门作用域 + q/dept 筛选）
    POST /ar/contracts  — 新增合同（可同时传 parties / project_ids 建立关联）
    """
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied

    if request.method == 'GET':
        qs = _ar_dept_filter(Contract.objects.all(), request, dept_field='delivery_dept')
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(contract_no__icontains=q))
        dept = request.GET.get('dept', '').strip()
        if dept:
            qs = qs.filter(delivery_dept=dept)
        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
        total = qs.count()
        rows = [c.to_dict() for c in qs[(page - 1) * size: page * size]]
        return ok({'items': rows, 'total': total, 'page': page, 'size': size})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        name = (data.get('name') or '').strip()
        if not name:
            return err('合同名称不能为空')
        dept = (data.get('delivery_dept') or '').strip()
        if dept:
            if dept not in VALID_DEPARTMENTS:
                return err(f'无效交付部门: {dept}')
            denied = _dept_denied(request, dept, '无权操作此部门')
            if denied:
                return denied
        amount = data.get('amount')
        with transaction.atomic():
            ct = Contract(
                name=name,
                contract_no=(data.get('contract_no') or '').strip(),
                delivery_dept=dept,
                sign_date=_normalize_date(data.get('sign_date')) or None,
                amount=_dec(amount) if amount not in (None, '') else None,
                notes=(data.get('notes') or '').strip(),
            )
            ct.save()
            _sync_contract_links(ct, data, request)
        return ok(ct.to_dict(with_links=True))

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def contract_detail(request, pk):
    """GET /PUT /DELETE  /ar/contracts/<pk>（含 parties/projects 关联维护）"""
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    try:
        ct = Contract.objects.get(pk=pk)
    except Contract.DoesNotExist:
        return err('合同不存在', 404)
    # 部门访问控制
    if request.pk_role != 'super_admin' and ct.delivery_dept and ct.delivery_dept not in request.pk_depts:
        return err('无权访问', 403)

    if request.method == 'GET':
        return ok(ct.to_dict(with_links=True))

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        if 'name' in data:
            name = (data['name'] or '').strip()
            if not name:
                return err('合同名称不能为空')
            ct.name = name
        if 'contract_no' in data:
            ct.contract_no = (data['contract_no'] or '').strip()
        if 'delivery_dept' in data:
            dept = (data['delivery_dept'] or '').strip()
            if dept and dept not in VALID_DEPARTMENTS:
                return err(f'无效交付部门: {dept}')
            if dept:
                denied = _dept_denied(request, dept, '无权操作目标部门')
                if denied:
                    return denied
            ct.delivery_dept = dept
        if 'sign_date' in data:
            ct.sign_date = _normalize_date(data['sign_date']) or None
        if 'amount' in data:
            amt = data['amount']
            ct.amount = _dec(amt) if amt not in (None, '') else None
        if 'notes' in data:
            ct.notes = (data['notes'] or '').strip()
        with transaction.atomic():
            ct.save()
            _sync_contract_links(ct, data, request)
        return ok(ct.to_dict(with_links=True))

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        ct.delete()   # 级联删除 parties / project_links（不删客户与项目本体）
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


