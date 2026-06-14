"""客户管理（customers）业务域视图：客户列表/详情、等级批量标注与回流校准、
从项目同步、批量删除（清理孤儿客户）。共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

# ──────────────────────────────────────────────────────────────────────────────
# 客户管理 (customers)
# ──────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@pk_required()
def customers(request):
    """GET  /ar/customers   — 分页列表（with_stats=1 附带应收聚合）
    POST /ar/customers   — 新增客户
    """
    # 客户管理隶属「项目台账」模块，与合同接口一致按 ar_projects 页面权限把关。
    # 认证由 @pk_required() 保证；部门隔离由下方 dept 过滤 / 写入由 _write_denied 处理。
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied

    if request.method == 'GET':
        from django.db.models.functions import Coalesce
        from django.db.models import Exists, OuterRef
        today = datetime.date.today()
        # 客户按事业部隔离 + 顶部全局范围（?depts）一并生效，与项目/应收口径一致；
        # _ar_dept_filter 对无授权部门的用户返回空集（杜绝「无部门=看全部」漏洞）。
        qs = _ar_dept_filter(Customer.objects.all(), request, dept_field='delivery_dept')
        # 共享业务岗位（ar_shared_only，如销售BP）：仅纳入有共享项目的客户，
        # 且其应收聚合仅统计共享项目，避免经客户视图泄露自营业务财务。
        shared_only = False
        if request.pk_role != 'super_admin':
            _perms = get_request_perms(request)
            shared_only = bool(_perms and _perms.get('ar_shared_only'))
        if shared_only:
            qs = qs.filter(Exists(
                ARProject.objects.filter(customer_id=OuterRef('pk'), is_shared=True)))
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(contact__icontains=q) | Q(notes__icontains=q))
        level = request.GET.get('level', '').strip()
        if level:
            qs = qs.filter(level=level)
        status_f = request.GET.get('status', '').strip()
        if status_f:
            qs = qs.filter(status=status_f)
        # 事业部筛选：直接按客户自身的交付部门
        dept = request.GET.get('dept', '').strip()
        if dept:
            qs = qs.filter(delivery_dept=dept)

        # 数据库级聚合应收（客户已按事业部隔离 → 其全部应收即本部门，无需逐条过滤部门）
        # shared_only 岗位：所有计数/求和叠加「项目为共享业务」过滤。
        _base = Q(projects__is_shared=True) if shared_only else None
        def _money(extra=None):
            f = _base
            if extra is not None:
                f = (f & extra) if f is not None else extra
            kw = {'filter': f} if f is not None else {}
            return Coalesce(Sum('projects__ar_records__outstanding_amount', **kw),
                            Value(0), output_field=DecimalField())
        _inv_kw = {'filter': _base} if _base is not None else {}
        qs = qs.annotate(
            s_project_count=Count('projects', filter=_base, distinct=True),
            s_invoiced=Coalesce(Sum('projects__ar_records__actual_invoice_amount', **_inv_kw),
                                Value(0), output_field=DecimalField()),
            s_outstanding=_money(),
            s_overdue=_money(Q(projects__ar_records__due_date__lt=today,
                              projects__ar_records__outstanding_amount__gt=0)),
        )

        # 数据库级排序：跨所有分页生效，不再分页时临时算
        SORT_MAP = {
            'outstanding': 's_outstanding', 'overdue': 's_overdue', 'invoiced': 's_invoiced',
            'project_count': 's_project_count', 'name': 'name', 'level': 'level',
            'customer_date': 'customer_date', 'created_at': 'created_at',
        }
        sort = SORT_MAP.get(request.GET.get('sort', 'outstanding'), 's_outstanding')
        direction = '' if request.GET.get('dir', 'desc') == 'asc' else '-'
        qs = qs.order_by(direction + sort, 'name')

        page = max(1, int(request.GET.get('page', 1) or 1))
        size = min(200, max(1, int(request.GET.get('size', 50) or 50)))
        total = qs.count()
        page_customers = list(qs[(page - 1) * size: page * size])
        rows = [{
            'id': c.id, 'name': c.name, 'delivery_dept': c.delivery_dept,
            'level': c.level, 'status': c.status, 'contact': c.contact,
            'customer_date': str(c.customer_date) if c.customer_date else None,
            'notes': c.notes,
            'created_at': c.created_at.isoformat() if c.created_at else None,
            'updated_at': c.updated_at.isoformat() if c.updated_at else None,
            'project_count': c.s_project_count,
            'invoiced': float(c.s_invoiced),
            'outstanding': float(c.s_outstanding),
            'overdue': float(c.s_overdue),
        } for c in page_customers]
        return ok({'items': rows, 'total': total, 'page': page, 'size': size})

    if request.method == 'POST':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        name = (data.get('name') or '').strip()
        if not name:
            return err('客户名称不能为空')
        dept = (data.get('delivery_dept') or '').strip()
        # 客户按事业部隔离 → 新建必须指定事业部，杜绝再产生无部门孤儿客户
        if not dept:
            return err('请选择客户所属事业部（客户按事业部隔离）')
        if dept not in VALID_DEPARTMENTS:
            return err(f'无效交付部门「{dept}」')
        if request.pk_role != 'super_admin' and dept not in request.pk_depts:
            return err(f'无权在事业部「{dept}」下新建客户')
        # 客户按 (名称 + 事业部) 隔离：同名客户在不同部门可各建一个
        if Customer.objects.filter(name=name, delivery_dept=dept).exists():
            return err(f'客户「{name}」在「{dept or "未指定部门"}」已存在')
        st = (data.get('status') or '运作中').strip()
        if st not in dict(Customer.STATUS_CHOICES):
            st = '运作中'
        c = Customer(
            name=name,
            delivery_dept=dept,
            level=(data.get('level') or '').strip(),
            status=st,
            contact=(data.get('contact') or '').strip(),
            customer_date=_normalize_date(data.get('customer_date')) or None,
            notes=(data.get('notes') or '').strip(),
        )
        c.save()
        return ok(c.to_dict())

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def customers_bulk_tag_level(request):
    """POST /customers/bulk-tag-level  —  批量为客户打/改等级。

    Body: { "ids": [1,2,3], "level": "A级" }
    或   : { "all": true, "level": "A级", "q": "...", "level_filter": "..." }
      all=true 时对当前筛选全集（搜索 q + 当前等级 level_filter）打标，限 5000 条。
    level 传空字符串 = 清空等级（取消分级）。
    """
    denied = _page_denied(request, 'ar_projects') or _write_denied(request)
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    # 部门隔离由下方 dept 过滤处理。
    # （历史遗留的 'dept_admin'/'user' 并非真实角色，会误伤所有非超管用户）

    data = _parse_body(request)
    level = (data.get('level') or '').strip()
    if level and level not in VALID_CUSTOMER_LEVELS:
        return err(f'无效客户等级「{level}」，可选：{"、".join(VALID_CUSTOMER_LEVELS)}')

    all_flag = data.get('all') in (True, 'true', '1')
    ids = data.get('ids')

    if all_flag:
        # 部门隔离：非超管只能批量操作自己有权部门的客户（无授权部门→空集）
        qs = _ar_dept_filter(Customer.objects.all(), request, dept_field='delivery_dept')
        q = (data.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(contact__icontains=q) | Q(notes__icontains=q))
        level_filter = (data.get('level_filter') or '').strip()
        if level_filter:
            qs = qs.filter(level=level_filter)
        dept_filter = (data.get('dept') or '').strip()
        if dept_filter:
            qs = qs.filter(delivery_dept=dept_filter)
        cnt = qs.count()
        if cnt == 0:
            return err('当前筛选没有匹配的客户')
        if cnt > 5000:
            return err('选中客户超过5000个，请缩小筛选范围后再批量操作')
        id_list = list(qs.values_list('id', flat=True))
        updated = qs.update(level=level)
    else:
        if not ids or not isinstance(ids, list):
            return err('请传入 ids 数组或 all=true')
        try:
            id_list = [int(i) for i in ids]
        except (TypeError, ValueError):
            return err('ids 必须为整数数组')
        # 部门隔离：仅保留用户有权部门的客户（无授权部门→空集，杜绝按 id 跨部门越权）
        cqs = _ar_dept_filter(
            Customer.objects.filter(pk__in=id_list), request, dept_field='delivery_dept')
        id_list = list(cqs.values_list('id', flat=True))
        updated = cqs.update(level=level)
    # 以客户为准：客户等级变更后，同步镜像到其名下所有项目
    ARProject.objects.filter(customer_id__in=id_list).update(customer_level=level)

    action = f'设置等级为「{level}」' if level else '清空等级'
    return ok({'updated': updated, 'level': level,
               'message': f'{action}，共更新 {updated} 个客户'})


def _reconcile_customer_levels(customer_ids):
    """以客户为准对齐「客户等级 ↔ 项目等级」。
    每个客户取规范等级 = 客户已有等级；客户为空则取其项目中出现最多的非空等级；
    再把规范等级回写客户、镜像到该客户全部项目。返回（对齐的客户数）。"""
    from collections import Counter
    aligned = 0
    for c in Customer.objects.filter(id__in=list(customer_ids)).iterator():
        proj_levels = [(pl or '').strip() for pl in
                       ARProject.objects.filter(customer_id=c.id).values_list('customer_level', flat=True)]
        canonical = (c.level or '').strip()
        if not canonical:
            nonempty = [pl for pl in proj_levels if pl]
            if nonempty:
                canonical = Counter(nonempty).most_common(1)[0][0]
        if not canonical:
            continue
        touched = False
        if (c.level or '').strip() != canonical:
            c.level = canonical
            c.save(update_fields=['level', 'updated_at'])
            touched = True
        n = (ARProject.objects.filter(customer_id=c.id)
             .exclude(customer_level=canonical).update(customer_level=canonical))
        if touched or n:
            aligned += 1
    return aligned


@csrf_exempt
@pk_required()
def customers_sync_from_projects(request):
    """POST /customers/sync-from-projects — 从项目台账回填客户名单 + 对齐等级。

    历史项目（在「客户正名」之前导入的）可能有客户名称但未挂客户实体。
    本接口：①扫描有客户名称却未挂客户的项目，按唯一客户名 get_or_create 客户并挂接；
    ②以客户为准对齐「客户等级↔项目等级」（同一客户所有项目等级统一）。
    一个客户对应多个项目（不合并金额、不动应收）。幂等：重复点击安全。
    部门权限：仅同步当前用户有权部门的项目。
    """
    denied = _page_denied(request, 'ar_projects') or _write_denied(request)
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    # 部门隔离由下方 dept 过滤处理。
    # （历史遗留的 'dept_admin'/'user' 并非真实角色，会误伤所有非超管用户）

    qs = _ar_dept_filter(
        ARProject.objects.filter(customer__isnull=True).exclude(customer_name=''), request)
    created = linked = 0
    for p in qs.iterator():
        name = (p.customer_name or '').strip()
        if not name:
            continue
        cust, was_created = Customer.objects.get_or_create(
            name=name, delivery_dept=p.delivery_dept or '',
            defaults={'level': p.customer_level or ''})
        if was_created:
            created += 1
        # 直接 update 挂接，避开 save 的派生重算副作用
        ARProject.objects.filter(pk=p.pk).update(customer=cust)
        linked += 1

    # 对齐等级：本用户有权部门项目所涉及的全部客户
    scoped_proj = _ar_dept_filter(ARProject.objects.filter(customer__isnull=False), request)
    cust_ids = set(scoped_proj.values_list('customer_id', flat=True))
    aligned = _reconcile_customer_levels(cust_ids)

    # 清理孤儿客户：名下 0 项目且无合同关联（项目台账已删但名单残留）。
    # 超管清理全局；事业部用户仅清理本部门的孤儿，避免误删他人数据。
    orphan_qs = Customer.objects.annotate(
        _np=Count('projects', distinct=True),
        _nc=Count('contract_links', distinct=True)).filter(_np=0, _nc=0)
    if request.pk_role != 'super_admin':
        orphan_qs = orphan_qs.filter(delivery_dept__in=(request.pk_depts or []))
    purged = orphan_qs.count()
    orphan_qs.delete()

    parts = []
    if created or linked:
        parts.append(f'新建 {created} 个客户、挂接 {linked} 个项目')
    if aligned:
        parts.append(f'对齐 {aligned} 个客户的等级')
    if purged:
        parts.append(f'清理 {purged} 个名下无项目的孤儿客户')
    msg = ('同步完成：' + '；'.join(parts)) if parts else '客户名单与等级已是最新，无需处理'
    return ok({'created_customers': created, 'linked_projects': linked,
               'aligned_levels': aligned, 'purged_orphans': purged, 'message': msg})


@csrf_exempt
@pk_required()
def customer_detail(request, pk):
    """GET /PUT /DELETE  /ar/customers/<pk>"""
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    try:
        c = Customer.objects.get(pk=pk)
    except Customer.DoesNotExist:
        return err('客户不存在', 404)
    # 客户按事业部隔离：非超管只能操作自己有权部门的客户（无部门孤儿放行）
    if (request.pk_role != 'super_admin' and c.delivery_dept
            and c.delivery_dept not in request.pk_depts):
        return err('无权访问该客户', 403)

    if request.method == 'GET':
        d = c.to_dict()
        today = datetime.date.today()
        # 该客户的项目 + 每个项目的应收聚合（部门作用域；ar_shared_only 仅见共享业务）
        proj_qs = _ar_dept_filter(
            ARProject.objects.filter(customer_id=pk), request,
            shared_field='is_shared').order_by('short_name')
        proj_ids = [p.id for p in proj_qs]
        rec_qs = _ar_dept_filter(
            ARRecord.objects.filter(project_id__in=proj_ids), request)
        per_proj = {pid: {'invoiced': 0.0, 'outstanding': 0.0, 'overdue': 0.0, 'records': 0}
                    for pid in proj_ids}
        for r in rec_qs.values('project_id').annotate(
                inv=Sum('actual_invoice_amount'), out_amt=Sum('outstanding_amount'),
                cnt=Count('id')):
            pp = per_proj[r['project_id']]
            pp['invoiced'] = float(r['inv'] or 0)
            pp['outstanding'] = float(r['out_amt'] or 0)
            pp['records'] = r['cnt']
        for r in (rec_qs.filter(due_date__lt=today, outstanding_amount__gt=0)
                  .values('project_id').annotate(ov=Sum('outstanding_amount'))):
            per_proj[r['project_id']]['overdue'] = float(r['ov'] or 0)
        projects = []
        for p in proj_qs:
            pp = per_proj.get(p.id, {})
            projects.append({
                'id': p.id, 'project_no': p.project_no,
                'short_name': p.short_name, 'customer_name': p.customer_name,
                'delivery_dept': p.delivery_dept, 'business_mode': p.business_mode,
                'status': p.status,
                'invoiced': pp.get('invoiced', 0.0), 'outstanding': pp.get('outstanding', 0.0),
                'overdue': pp.get('overdue', 0.0), 'records': pp.get('records', 0),
            })
        d['projects'] = projects
        d['stats'] = {
            'project_count': len(projects),
            'invoiced': round(sum(p['invoiced'] for p in projects), 2),
            'outstanding': round(sum(p['outstanding'] for p in projects), 2),
            'overdue': round(sum(p['overdue'] for p in projects), 2),
        }
        d['stats']['collected'] = round(d['stats']['invoiced'] - d['stats']['outstanding'], 2)
        return ok(d)

    if request.method == 'PUT':
        denied = _write_denied(request)
        if denied:
            return denied
        data = _parse_body(request)
        name_changed = False
        if 'name' in data:
            name = (data['name'] or '').strip()
            if not name:
                return err('客户名称不能为空')
            if Customer.objects.filter(name=name, delivery_dept=c.delivery_dept).exclude(pk=pk).exists():
                return err(f'客户名称「{name}」在「{c.delivery_dept or "未指定部门"}」已被占用')
            name_changed = (c.name != name)
            c.name = name
        level_changed = 'level' in data
        for field in ('level', 'contact', 'notes'):
            if field in data:
                setattr(c, field, (data[field] or '').strip())
        if 'status' in data:
            st = (data['status'] or '').strip()
            if st not in dict(Customer.STATUS_CHOICES):
                return err(f'无效客户状态「{st}」，可选：运作中/中断/结束')
            c.status = st
        if 'customer_date' in data:
            c.customer_date = _normalize_date(data['customer_date']) or None
        c.save()
        # 以客户为准：等级变更同步镜像到该客户名下所有项目
        if level_changed:
            ARProject.objects.filter(customer_id=c.id).update(customer_level=c.level)
        # 客户改名 → 同步名下项目的 customer_name 文本字段，保持两边一致
        if name_changed:
            ARProject.objects.filter(customer_id=c.id).update(customer_name=c.name)
        # 一键下发：把客户状态应用到名下所有项目（项目独立状态，仅在显式请求时下发）
        if data.get('push_status'):
            ARProject.objects.filter(customer_id=c.id).update(status=c.status)
        return ok(c.to_dict())

    if request.method == 'DELETE':
        denied = _delete_denied(request)
        if denied:
            return denied
        # 名下还有项目时禁删：否则项目 customer_id 置空、客户名文本悬空，
        # 下次保存项目会按同名重建客户，等级真相源断链
        linked = ARProject.objects.filter(customer_id=c.pk).count()
        if linked:
            return err(f'客户「{c.name}」名下还有 {linked} 个项目，不能删除；'
                       f'请先删除或改挂这些项目（项目台账中修改客户名称即可改挂）')
        c.delete()
        return ok({'deleted': pk})

    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def customers_bulk_delete(request):
    """POST /ar/customers/bulk-delete  body {ids:[int,...]}
    批量删除客户。与单删同口径的保护：名下仍有项目或有合同关联的客户跳过不删，
    并在返回中逐个说明原因；部门作用域与删除权限约束同列表。单次上限 1000。"""
    denied = _page_denied(request, 'ar_projects')
    if denied:
        return denied
    if request.method != 'POST':
        return err('POST only', 405)
    denied = _delete_denied(request)
    if denied:
        return denied

    body = _parse_body(request)
    ids = body.get('ids') or []
    if not isinstance(ids, list) or not ids:
        return err('请提供要删除的客户 ids')
    try:
        ids = [int(i) for i in ids]
    except (ValueError, TypeError):
        return err('ids 必须为整数列表')
    if len(ids) > 1000:
        return err('单次删除上限 1000 个，请分批操作')

    qs = _ar_dept_filter(Customer.objects.filter(pk__in=ids), request,
                         dept_field='delivery_dept')
    qs = qs.annotate(_np=Count('projects', distinct=True),
                     _nc=Count('contract_links', distinct=True))
    deletable, skipped = [], []
    for c in qs:
        if c._np:
            skipped.append(f'「{c.name}」名下还有 {c._np} 个项目，未删除')
        elif c._nc:
            skipped.append(f'「{c.name}」有 {c._nc} 个合同关联，未删除')
        else:
            deletable.append(c.pk)
    if deletable:
        Customer.objects.filter(pk__in=deletable).delete()
    msg = f'已删除 {len(deletable)} 个客户'
    if skipped:
        msg += f'，{len(skipped)} 个被保护跳过'
    return ok({'deleted': len(deletable), 'skipped': len(skipped),
               'skipped_reasons': skipped[:50], 'message': msg})


# ──────────────────────────────────────────────────────────────────────────────
