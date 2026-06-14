"""资金池（cash pool）业务域视图：每事业部一池，期初+收支流水推算账面余额，
刚性/在途流出做预判；池间划拨的校验、透支防护与审批。
共享基座来自 _common。"""
from ._common import *  # noqa: F401,F403

# ══════════════════════════════════════════════════════════════════════════════
# 资金池 (cash pool) — 每事业部一池：期初 + 收支流水推算账面余额，刚性/在途流出做预判
# ══════════════════════════════════════════════════════════════════════════════

def _pool_visible_depts(request):
    """可见池子 = 授权部门 ∩ 全局激活范围（?depts），与其他模块的范围口径一致。"""
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


def _pool_actual_flows(dept, start, end):
    """(start, end] 区间的实际现金流（口径与现金流分析一致）。
    返回 (collected, adv_recv, paid, prepaid_offset, adv_paid, t_in, t_out)。"""
    collected = _dec(ARPayment.objects.filter(
        ar_record__delivery_dept=dept,
        payment_date__gt=start, payment_date__lte=end)
        .exclude(source='预收抵扣').aggregate(s=Sum('amount'))['s'])
    adv = (AdvanceRecord.objects.filter(
        delivery_dept=dept, occur_date__gt=start, occur_date__lte=end)
        .values('direction').annotate(s=Sum('advance_amount')))
    adv_map = {r['direction']: _dec(r['s']) for r in adv}
    paid = _dec(PaymentInstallment.objects.filter(
        payment__department=dept,
        pay_date__gt=start, pay_date__lte=end).aggregate(s=Sum('pay_amount'))['s'])
    # 预付核销冲抵：现金已在预付发生时流出，核销时不再是现金事件 → 从实付中扣除
    prepaid_offset = _dec(AdvanceWriteoff.objects.filter(
        payment__department=dept,
        writeoff_date__gt=start, writeoff_date__lte=end).aggregate(s=Sum('amount'))['s'])
    # 调拨：只有已生效（approved）的才是真实现金事件；待审批/已拒绝不动余额
    t_in = _dec(CashPoolTransfer.objects.filter(
        to_dept=dept, status='approved',
        transfer_date__gt=start, transfer_date__lte=end)
        .aggregate(s=Sum('amount'))['s'])
    t_out = _dec(CashPoolTransfer.objects.filter(
        from_dept=dept, status='approved',
        transfer_date__gt=start, transfer_date__lte=end)
        .aggregate(s=Sum('amount'))['s'])
    return (collected, adv_map.get('预收', Decimal('0')), paid, prepaid_offset,
            adv_map.get('预付', Decimal('0')), t_in, t_out)


def _pool_balance(dept, cfg, today):
    """池子当前账面余额 = 期初 + (期初日, 今天] 的净现金流。"""
    c, ar_, p, po, ap, ti, to_ = _pool_actual_flows(dept, cfg.initial_date, today)
    return cfg.initial_amount + c + ar_ - (p - po) - ap + ti - to_


def _pool_metrics(dept, cfg, today):
    """单个池子的全部指标：账面余额、资金预警线、刚性/在途流出、预期流入、余额预测。"""
    start = cfg.initial_date

    c, ar_, p, po, ap, ti, to_ = _pool_actual_flows(dept, start, today)
    balance = (cfg.initial_amount + c + ar_ - (p - po) - ap + ti - to_)

    # ── 刚性流出：付款台账已审批待付（remaining>0），按计划日期分窗。
    #    已用预付核销冲抵的部分不再需要现金，故一并扣除（与余额口径对称）。
    #    已付额必须用关联子查询（_paid_subq）而非 Sum('installments__...')：
    #    JOIN 聚合会让 rem__gt=0 落到 HAVING，其中裸列 plan_adjustment/
    #    total_amount/prepaid_offset_amount 不在 GROUP BY 里——SQLite 容忍，
    #    生产 MySQL 报 1054 Unknown column in 'having clause'。
    #    子查询版无 GROUP BY，过滤走 WHERE，两种库都安全（与付款列表口径同源）──
    pay_qs = (Payment.objects.filter(department=dept)
              .annotate(paid_sum=_paid_subq())
              .annotate(plan=Coalesce('plan_adjustment', 'total_amount'))
              .annotate(rem=F('plan') - F('paid_sum') - F('prepaid_offset_amount'))
              .filter(rem__gt=0))

    def _win(qs):
        return _dec(qs.aggregate(s=Sum('rem'))['s'])
    d30, d60, d90 = (today + datetime.timedelta(days=n) for n in (30, 60, 90))
    committed = {
        'overdue': _win(pay_qs.filter(planned_date__lte=today)),
        'd30': _win(pay_qs.filter(planned_date__gt=today, planned_date__lte=d30)),
        'd60': _win(pay_qs.filter(planned_date__gt=d30, planned_date__lte=d60)),
        'd90': _win(pay_qs.filter(planned_date__gt=d60, planned_date__lte=d90)),
    }
    committed['total'] = sum(committed.values())

    # ── 在途流出：审批记录（未排款）。已批待排=大概率近期变刚性；审批中=不确定。
    #    另含待审批的调拨出款申请——批准即出账，不计会高估可用余额 ─────────────
    pipe = (ApprovalRecord.objects.filter(department=dept, archived=False)
            .values('status').annotate(s=Sum('amount')))
    pipe_map = {r['status']: _dec(r['s']) for r in pipe}
    pipeline = {'approved': pipe_map.get('approved', Decimal('0')),
                'pending': pipe_map.get('pending', Decimal('0')),
                'transfer_out_pending': _dec(CashPoolTransfer.objects.filter(
                    from_dept=dept, status='pending').aggregate(s=Sum('amount'))['s'])}

    # ── 预期流入：未结清应收按到期日分窗；已逾期的单列（不计入预判，视作上行空间）──
    ar_qs = ARRecord.objects.filter(delivery_dept=dept, outstanding_amount__gt=0)

    def _ein(lo, hi):
        return _dec(ar_qs.filter(due_date__gt=lo, due_date__lte=hi)
                    .aggregate(s=Sum('outstanding_amount'))['s'])
    expected_in = {
        'd30': _ein(today, d30),
        'd60': _ein(d30, d60),
        'd90': _ein(d60, d90),
        'overdue_outstanding': _dec(ar_qs.filter(due_date__lte=today)
                                    .aggregate(s=Sum('outstanding_amount'))['s']),
    }

    # ── 余额预测：现余额 + 预期流入 − 刚性流出（逾期刚性视作立即要付）────────────
    level30 = balance + expected_in['d30'] - committed['overdue'] - committed['d30']
    level60 = level30 + expected_in['d60'] - committed['d60']
    level90 = level60 + expected_in['d90'] - committed['d90']
    # 审慎口径：已批待排的在途支出与待批调拨出款，按30天内全部付出计算
    d30_pess = level30 - pipeline['approved'] - pipeline['transfer_out_pending']
    projection = {'d30': str(level30), 'd60': str(level60), 'd90': str(level90),
                  'd30_with_pipeline': str(d30_pess)}

    # ── 资金预警线：超管手设固定额度优先；未设则按未来 warning_days 天
    #    刚性流出（含逾期未付）动态推算 ────────────────────────────────────────
    if cfg.warning_amount is not None:
        warn_amount = cfg.warning_amount
        warn_mode = 'fixed'
    else:
        wd = today + datetime.timedelta(days=cfg.warning_days or 30)
        warn_amount = committed['overdue'] + _win(
            pay_qs.filter(planned_date__gt=today, planned_date__lte=wd))
        warn_mode = 'dynamic'
    if balance < warn_amount:
        status = 'danger'
    elif level60 < 0 or d30_pess < 0:
        status = 'warn'
    else:
        status = 'ok'

    # ── 健康指标：近90天口径 ─────────────────────────────────────────────────
    t90 = today - datetime.timedelta(days=90)
    s90 = max(start, t90)
    c9, ar9, p9, po9, ap9, ti9, to9 = _pool_actual_flows(dept, s90, today)
    span = max(1, (today - s90).days)
    in90 = c9 + ar9
    out90 = (p9 - po9) + ap9
    runway = float(balance) / (float(out90) / span) if out90 > 0 and balance > 0 else None
    health = {
        'runway_days': round(runway) if runway is not None else None,
        'self_rate': round(float(in90) / float(out90) * 100, 1) if out90 > 0 else None,
        'net90': str(in90 - out90),
    }

    return {
        'dept': dept,
        'configured': True,
        'config': cfg.to_dict(),
        'balance': str(balance),
        'parts': {
            'initial': str(cfg.initial_amount),
            'collected': str(c), 'advance_received': str(ar_),
            'paid': str(p - po), 'advance_paid': str(ap),
            'transfer_in': str(ti), 'transfer_out': str(to_),
        },
        'warning': {'amount': str(warn_amount), 'status': status, 'mode': warn_mode},
        'committed': {k: str(v) for k, v in committed.items()},
        'pipeline': {k: str(v) for k, v in pipeline.items()},
        'expected_in': {k: str(v) for k, v in expected_in.items()},
        'projection': projection,
        'health': health,
    }


@csrf_exempt
@pk_required()
def cash_pool(request):
    """资金池总览：可见事业部各一池（账面余额/资金预警线/刚性+在途流出/预期流入/余额预测）。"""
    denied = _page_denied(request, 'ar_cashflow')
    if denied:
        return denied
    if request.method != 'GET':
        return err('Method not allowed', 405)

    today = datetime.date.today()
    depts = _pool_visible_depts(request)
    try:
        cfgs = {c.delivery_dept: c for c in CashPoolConfig.objects.filter(delivery_dept__in=depts)}
    except Exception as exc:
        import traceback
        logger.error('cash_pool: config query failed: %s\n%s', exc, traceback.format_exc())
        return err(f'资金池配置读取失败：{exc}。'
                   f'若提示字段/列不存在，说明数据库迁移未应用到当前服务所连的库——'
                   f'请在服务器运行环境（与启动服务相同的环境变量，含 MYSQL_ADDRESS）'
                   f'执行 python manage.py migrate 后重启服务', 500)

    pools = []
    for dept in depts:
        cfg = cfgs.get(dept)
        if cfg is None:
            pools.append({'dept': dept, 'configured': False})
            continue
        try:
            pools.append(_pool_metrics(dept, cfg, today))
        except Exception as exc:
            import traceback
            logger.error('cash_pool: _pool_metrics failed dept=%s: %s\n%s',
                         dept, exc, traceback.format_exc())
            pools.append({'dept': dept, 'configured': True, 'error': str(exc)})

    configured = [p for p in pools if p.get('configured') and not p.get('error')]
    group = None
    if configured:
        def _sumf(getter):
            return str(sum(Decimal(getter(p)) for p in configured))
        group = {
            'balance': _sumf(lambda p: p['balance']),
            'warning_amount': _sumf(lambda p: p['warning']['amount']),
            'committed_total': _sumf(lambda p: p['committed']['total']),
            'pipeline_approved': _sumf(lambda p: p['pipeline']['approved']),
            'pipeline_pending': _sumf(lambda p: p['pipeline']['pending']),
            'projection_d30': _sumf(lambda p: p['projection']['d30']),
            'projection_d60': _sumf(lambda p: p['projection']['d60']),
            'projection_d90': _sumf(lambda p: p['projection']['d90']),
            'danger_count': sum(1 for p in configured if p['warning']['status'] == 'danger'),
            'warn_count': sum(1 for p in configured if p['warning']['status'] == 'warn'),
        }
    return ok({'pools': pools, 'group': group, 'today': str(today)})


@csrf_exempt
@pk_required(roles=['super_admin'])
def cash_pool_config(request):
    """池配置（仅超管）：GET 列表 / POST 按事业部 upsert 期初基准。"""
    if request.method == 'GET':
        return ok({'items': [c.to_dict() for c in CashPoolConfig.objects.all()],
                   'departments': DEPARTMENTS})
    if request.method == 'POST':
        data = _parse_body(request)
        dept = (data.get('delivery_dept') or '').strip()
        if dept not in VALID_DEPARTMENTS:
            return err('无效的事业部')
        initial_date = _normalize_date(data.get('initial_date'))
        if not initial_date:
            return err('期初基准日必填（YYYY-MM-DD）')
        try:
            init_d = datetime.date.fromisoformat(str(initial_date)[:10])
        except (ValueError, TypeError):
            return err('期初基准日格式错误')
        if init_d > datetime.date.today():
            return err('期初基准日不能晚于今天（期初是已发生的账面事实）')
        try:
            initial_amount = Decimal(str(data.get('initial_amount', 0) or 0))
        except (InvalidOperation, ValueError):
            return err('期初金额格式错误')
        try:
            warning_days = max(7, min(120, int(data.get('warning_days', 30) or 30)))
        except (ValueError, TypeError):
            warning_days = 30
        warning_amount = None
        raw_warn = data.get('warning_amount')
        if raw_warn not in (None, ''):
            try:
                warning_amount = Decimal(str(raw_warn))
            except (InvalidOperation, ValueError):
                return err('资金预警线金额格式错误')
            if warning_amount < 0:
                return err('资金预警线不能为负数')
        cfg, _ = CashPoolConfig.objects.update_or_create(
            delivery_dept=dept,
            defaults={'initial_date': initial_date, 'initial_amount': initial_amount,
                      'warning_days': warning_days, 'warning_amount': warning_amount,
                      'notes': (data.get('notes') or '').strip(),
                      'updated_by': request.pk_user})
        return ok(cfg.to_dict())
    return err('Method not allowed', 405)


def _validate_transfer_payload(data):
    """调拨公共校验。返回 (from_dept, to_dept, amount, tr_date, err_response)。"""
    f, t = (data.get('from_dept') or '').strip(), (data.get('to_dept') or '').strip()
    if f not in VALID_DEPARTMENTS or t not in VALID_DEPARTMENTS:
        return None, None, None, None, err('无效的事业部')
    if f == t:
        return None, None, None, None, err('调出与调入不能是同一个池子')
    try:
        amount = Decimal(str(data.get('amount') or 0))
    except (InvalidOperation, ValueError):
        return None, None, None, None, err('金额格式错误')
    if amount <= 0:
        return None, None, None, None, err('调拨金额必须大于0')
    tr_date = _normalize_date(data.get('transfer_date')) or str(datetime.date.today())
    try:
        tr_date_d = datetime.date.fromisoformat(str(tr_date)[:10])
    except (ValueError, TypeError):
        return None, None, None, None, err('调拨日期格式错误')
    if tr_date_d > datetime.date.today():
        return None, None, None, None, err('调拨日期不能晚于今天（调拨以实际发生日入账）')
    return f, t, amount, tr_date_d, None


def _transfer_guards(f, t, tr_date_d, lock=False):
    """期初配置与日期守恒校验。lock=True 时锁定两侧配置行（须在事务内），
    串行化并发的余额检查，防止两笔同时通过校验后合计透支。
    返回 (cfg_f, cfg_t, err_response)。"""
    qs = CashPoolConfig.objects.select_for_update() if lock else CashPoolConfig.objects
    cfgs = {c.delivery_dept: c for c in qs.filter(delivery_dept__in=[f, t])}
    cfg_f, cfg_t = cfgs.get(f), cfgs.get(t)
    # 两池都须已配置期初，且调拨日期不得早于任一侧期初基准日——
    # 否则一侧计入一侧忽略，集团合计≠各池之和（台账不守恒）
    if not cfg_f or not cfg_t:
        return None, None, err('调出/调入池需先在「池配置」中设置期初基准')
    if tr_date_d < cfg_f.initial_date or tr_date_d < cfg_t.initial_date:
        return None, None, err('调拨日期不能早于两侧池子的期初基准日（会造成台账不守恒）')
    return cfg_f, cfg_t, None


def _transfer_overdraft_err(f, cfg_f, amount):
    """不允许透支调拨：调出额不得超过调出池当前账面余额。"""
    balance = _pool_balance(f, cfg_f, datetime.date.today())
    if amount > balance:
        return err(f'调出池「{f}」当前可用余额 {balance:,.2f} 元，'
                   f'不足以调出 {amount:,.2f} 元（不允许透支调拨）')
    return None


@csrf_exempt
@pk_required()
def cash_pool_transfers(request):
    """池间资金调拨。
    GET：列表（非超管只看与自己部门相关的）。
    POST：超管直接调拨即时生效；事业部用户提交「调拨申请」（status=pending），
          须经调出方事业部（或超管）审批后生效，且发起人须与调出/调入一侧同部门。"""
    if request.method == 'GET':
        denied = _page_denied(request, 'ar_cashflow')
        if denied:
            return denied
        qs = CashPoolTransfer.objects.all()
        if request.pk_role != 'super_admin':
            mine = request.pk_depts or []
            qs = qs.filter(Q(from_dept__in=mine) | Q(to_dept__in=mine))
        try:
            return ok({'items': [t.to_dict() for t in qs[:200]]})
        except Exception as exc:
            import traceback
            logger.error('cash_pool_transfers: list failed: %s\n%s', exc, traceback.format_exc())
            return err(f'调拨台账读取失败：{exc}。'
                       f'若提示字段/列不存在，请在服务器运行环境执行 '
                       f'python manage.py migrate 后重启服务', 500)
    if request.method == 'POST':
        data = _parse_body(request)
        f, t, amount, tr_date_d, bad = _validate_transfer_payload(data)
        if bad:
            return bad
        common = {'expected_return_date': _normalize_date(data.get('expected_return_date')),
                  'notes': (data.get('notes') or '').strip(), 'created_by': request.pk_user}

        if request.pk_role == 'super_admin':
            # 集团统筹：直接生效。锁配置行串行化余额检查，防并发合计透支
            with transaction.atomic():
                cfg_f, cfg_t, bad = _transfer_guards(f, t, tr_date_d, lock=True)
                if bad:
                    return bad
                bad = _transfer_overdraft_err(f, cfg_f, amount)
                if bad:
                    return bad
                tr = CashPoolTransfer.objects.create(
                    from_dept=f, to_dept=t, amount=amount, transfer_date=tr_date_d,
                    status='approved', reviewed_by=request.pk_user,
                    reviewed_at=timezone.now(), **common)
            return ok(tr.to_dict())

        # 事业部用户：提交调拨申请，待调出方审批
        denied = _write_denied(request)
        if denied:
            return denied
        mine = request.pk_depts or []
        if f not in mine and t not in mine:
            return err('只能发起与本部门相关的调拨申请（调出或调入一侧须为本部门）', 403, 403)
        cfg_f, cfg_t, bad = _transfer_guards(f, t, tr_date_d)
        if bad:
            return bad
        # 申请阶段不冻结资金、不动余额；透支在审批生效时校验
        tr = CashPoolTransfer.objects.create(
            from_dept=f, to_dept=t, amount=amount, transfer_date=tr_date_d,
            status='pending', **common)
        return ok(tr.to_dict())
    return err('Method not allowed', 405)


@csrf_exempt
@pk_required()
def cash_pool_transfer_review(request, pk):
    """调拨申请审批：批准/拒绝。仅超管或调出方事业部（有写入权限）可审；
    不能审批自己发起的申请。批准时以审批日为实际生效日并校验余额充足。"""
    if request.method != 'POST':
        return err('Method not allowed', 405)
    try:
        tr = CashPoolTransfer.objects.get(pk=pk)
    except CashPoolTransfer.DoesNotExist:
        return err('调拨申请不存在', 404)
    if tr.status != 'pending':
        return err('该申请已处理（只有待审批的申请可以审批）')

    if request.pk_role != 'super_admin':
        if tr.from_dept not in (request.pk_depts or []):
            return err('只有调出方事业部（或超管）可以审批此申请', 403, 403)
        denied = _write_denied(request)
        if denied:
            return denied
        if tr.created_by_id and tr.created_by_id == request.pk_user.id:
            return err('不能审批自己发起的调拨申请', 403, 403)

    data = _parse_body(request)
    action = (data.get('action') or '').strip()
    review_notes = (data.get('review_notes') or '').strip()
    if action == 'reject':
        tr.status = 'rejected'
        tr.reviewed_by = request.pk_user
        tr.reviewed_at = timezone.now()
        tr.review_notes = review_notes
        tr.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes'])
        return ok(tr.to_dict())
    if action != 'approve':
        return err("action 须为 'approve' 或 'reject'")

    today = datetime.date.today()
    with transaction.atomic():
        cfg_f, cfg_t, bad = _transfer_guards(tr.from_dept, tr.to_dept, today, lock=True)
        if bad:
            return bad
        bad = _transfer_overdraft_err(tr.from_dept, cfg_f, tr.amount)
        if bad:
            return bad
        # 生效日以审批日为准：现金事件记在它实际发生的那天
        tr.status = 'approved'
        tr.transfer_date = today
        tr.reviewed_by = request.pk_user
        tr.reviewed_at = timezone.now()
        tr.review_notes = review_notes
        tr.save(update_fields=['status', 'transfer_date', 'reviewed_by',
                               'reviewed_at', 'review_notes'])
    return ok(tr.to_dict())


@csrf_exempt
@pk_required()
def cash_pool_transfer_detail(request, pk):
    """删除调拨：待审批的申请发起人可撤回；已生效/已拒绝的仅超管可删（余额回退）。"""
    if request.method != 'DELETE':
        return err('Method not allowed', 405)
    try:
        tr = CashPoolTransfer.objects.get(pk=pk)
    except CashPoolTransfer.DoesNotExist:
        return err('调拨记录不存在', 404)
    if request.pk_role != 'super_admin':
        if not (tr.status == 'pending' and tr.created_by_id
                and tr.created_by_id == request.pk_user.id):
            return err('只能撤回自己发起且尚未审批的调拨申请', 403, 403)
    tr.delete()
    return ok({'deleted': pk})


# 再导出本域全部公开名（含单下划线助手），使 `from ar.views import _x` 等旧引用不变。
__all__ = [n for n in dir() if not n.startswith('__')]
