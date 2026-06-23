import calendar
import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError

from paikuan.models import PaikuanUser


class Customer(models.Model):
    """客户主表 — 按事业部隔离的客户实体（同名客户在不同事业部是相互独立的两个客户）。"""
    STATUS_CHOICES = [('运作中', '运作中'), ('中断', '中断'), ('结束', '结束')]
    name = models.CharField('客户名称', max_length=200, db_index=True)
    delivery_dept = models.CharField('交付部门', max_length=50, blank=True, default='', db_index=True)
    level = models.CharField('客户等级', max_length=50, blank=True, default='')
    status = models.CharField('状态', max_length=10, choices=STATUS_CHOICES, default='运作中', db_index=True)
    contact = models.CharField('联系人', max_length=200, blank=True, default='')
    customer_date = models.DateField('建档日期', null=True, blank=True,
                                     help_text='可手工指定的客户日期（如 2026-01-01），区别于系统记录的创建时间')
    notes = models.TextField('备注', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_customers'
        ordering = ['name']
        unique_together = [('name', 'delivery_dept')]

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'delivery_dept': self.delivery_dept,
            'level': self.level,
            'status': self.status,
            'contact': self.contact,
            'customer_date': str(self.customer_date) if self.customer_date else None,
            'notes': self.notes,
            'project_count': self.projects.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ARProject(models.Model):
    """项目主表 — 每个合同/项目一行"""
    STATUS_CHOICES = [('运作中', '运作中'), ('中断', '中断'), ('结束', '结束')]
    project_no = models.CharField('项目编号', max_length=20, unique=True, db_index=True)
    customer_name = models.CharField('客户名称', max_length=200)
    short_name = models.CharField('项目简称', max_length=100, blank=True, default='')
    delivery_dept = models.CharField('交付部门', max_length=50, db_index=True)
    status = models.CharField('状态', max_length=10, choices=STATUS_CHOICES, default='运作中', db_index=True)
    sub_dept = models.CharField('二级部门', max_length=100, blank=True, default='')
    business_mode = models.CharField('业务模式', max_length=100, blank=True, default='')
    customer_level = models.CharField('客户等级', max_length=50, blank=True, default='')
    sales_contact = models.CharField('销售对接人', max_length=100)
    project_manager = models.CharField('项目负责人', max_length=100)
    is_shared = models.BooleanField('共享业务', default=False)
    has_contract = models.CharField('有无合同', max_length=2,
                                    choices=[('有', '有'), ('无', '无')], default='无')
    contract_date = models.DateField('签订日期', null=True, blank=True)
    reconciliation_days = models.IntegerField('合同对账期(天)', default=0)
    invoice_wait_days = models.IntegerField('开票等待期(天)', default=0)
    post_invoice_days = models.IntegerField('票后等待期(天)', default=0)
    total_days = models.IntegerField('总账期(天)', default=0)
    # 对账周期起始日（1~28）：1=自然月（月初到月末，默认）；如填 15 则账期月为
    # 每月15日~下月14日。只影响应收到期日推算的账期锚点；自然月聚合口径不变。
    cycle_start_day = models.PositiveSmallIntegerField('对账周期起始日', default=1)
    invoice_mode = models.CharField('开票模式', max_length=4,
                                    choices=[('全额', '全额'), ('差额', '差额')], default='全额')
    invoice_type = models.CharField('专票/普票/不开票', max_length=4,
                                    choices=[('专票', '专票'), ('普票', '普票'), ('不开票', '不开票')],
                                    blank=True, default='')
    tax_rate = models.DecimalField('税率', max_digits=6, decimal_places=4, default=Decimal('0'))
    notes = models.TextField('备注', blank=True, default='')
    # ── 智能导入扩展字段 ──────────────────────────────────────────────────────
    is_draft = models.BooleanField('草稿/待完善', default=False, db_index=True,
                                   help_text='导入时自动创建的未完善项目；补齐信息后置为 False')
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='projects',
                                 verbose_name='关联客户')
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='created_projects')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_projects'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['delivery_dept']),
            models.Index(fields=['project_manager']),
            models.Index(fields=['sales_contact']),
            models.Index(fields=['is_shared']),
        ]

    DEPT_PROJECT_PREFIX = {
        '劳务事业部': 'LW',
        '运输事业部': 'YS',
        '阔展事业部': 'KZ',
        '多式联运事业部': 'DL',
        '供应链事业部': 'GYL',
        '自营事业部': 'ZY',
    }

    def _gen_project_no(self):
        # 部门无对应简码（如导入时无法确定部门的草稿项目）回退用 'XX'，
        # 保证项目编号始终能生成、不致 500；草稿完善时改对部门会换正式编号前缀。
        dept_code = self.DEPT_PROJECT_PREFIX.get(self.delivery_dept, '') or 'XX'
        prefix = f'{dept_code}-{datetime.date.today().strftime("%Y%m%d")}-'
        with transaction.atomic():
            # 取当天该部门已有编号的最大序号 +1。用解析后的整数求最大值（而非字符串
            # 排序），对历史遗留的非定长编号也稳健。
            existing = (ARProject.objects.filter(project_no__startswith=prefix)
                        .select_for_update().values_list('project_no', flat=True))
            max_seq = -1
            for no in existing:
                try:
                    max_seq = max(max_seq, int(no.rsplit('-', 1)[-1]))
                except (ValueError, IndexError):
                    continue
            return f'{prefix}{max_seq + 1:04d}'

    def _autolink_customer(self):
        """客户按事业部隔离：项目挂到 (客户名 + 交付部门) 对应的客户实体。
        同名客户在不同事业部是两个独立客户。未挂 / 客户名或部门不一致时重新挂到
        get_or_create(name, delivery_dept)。失败不阻断项目保存。"""
        name = (self.customer_name or '').strip()
        if not name:
            return
        dept = self.delivery_dept or ''
        try:
            # 已挂且 名字+部门 都一致 → 无需重挂
            if (self.customer_id and (self.customer.name or '').strip() == name
                    and (self.customer.delivery_dept or '') == dept):
                return
            cust, created = Customer.objects.get_or_create(
                name=name, delivery_dept=dept, defaults={'level': self.customer_level or ''})
            # 换挂到已存在的客户实体：等级以该客户为准（单一真相源）。
            # 否则项目带着旧客户的等级进来，会被 _sync_level_with_customer 上推、
            # 冲掉新客户及其名下全部项目的等级。
            if not created and cust.id != self.customer_id and (cust.level or '').strip():
                self.customer_level = cust.level
            self.customer = cust
        except Exception:
            pass

    def _sync_level_with_customer(self):
        """客户等级以客户为准（单一真相源）：
        - 项目若显式填了等级且与客户不同 → 上推更新客户主等级，并同步该客户其余项目；
        - 最终项目等级镜像客户等级 → 同一客户所有项目等级永远一致。
        失败不阻断项目保存。"""
        if not self.customer_id:
            return
        try:
            cust = self.customer
            plv = (self.customer_level or '').strip()
            clv = (cust.level or '').strip()
            if plv and plv != clv:
                cust.level = plv
                cust.save(update_fields=['level', 'updated_at'])
                # 该客户的其它项目镜像跟上（本项目下面统一镜像）
                ARProject.objects.filter(customer_id=cust.id).exclude(pk=self.pk).update(customer_level=plv)
                clv = plv
            self.customer_level = clv
        except Exception:
            pass

    def save(self, *args, **kwargs):
        self.is_shared = (self.sales_contact != self.project_manager)
        self.total_days = (self.reconciliation_days + self.invoice_wait_days
                           + self.post_invoice_days)
        if self.invoice_type == '不开票':
            self.tax_rate = Decimal('0')
        # 客户名为准：未挂 / 改了客户名 → 重新挂到对应客户实体
        self._autolink_customer()
        # 客户等级以客户为准：拿到 customer 后做等级镜像/上推
        self._sync_level_with_customer()
        if self.project_no:
            return super().save(*args, **kwargs)
        # 自动生成编号：极少数并发下可能撞 unique，重试几次再放弃。
        from django.db import IntegrityError
        last_err = None
        for _ in range(5):
            self.project_no = self._gen_project_no()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError as e:
                last_err = e
                self.project_no = ''
        raise last_err

    def to_dict(self):
        return {
            'id': self.id,
            'project_no': self.project_no,
            'customer_name': self.customer_name,
            'short_name': self.short_name,
            'delivery_dept': self.delivery_dept,
            'status': self.status,
            'sub_dept': self.sub_dept,
            'business_mode': self.business_mode,
            'customer_level': self.customer_level,
            'sales_contact': self.sales_contact,
            'project_manager': self.project_manager,
            'is_shared': self.is_shared,
            'has_contract': self.has_contract,
            'contract_date': str(self.contract_date) if self.contract_date else None,
            'reconciliation_days': self.reconciliation_days,
            'invoice_wait_days': self.invoice_wait_days,
            'post_invoice_days': self.post_invoice_days,
            'total_days': self.total_days,
            'cycle_start_day': self.cycle_start_day,
            'invoice_mode': self.invoice_mode,
            'invoice_type': self.invoice_type,
            'tax_rate': str(self.tax_rate),
            'notes': self.notes,
            'is_draft': self.is_draft,
            'customer_id': self.customer_id,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class Contract(models.Model):
    """合同主表 — 一个合同可关联多个客户(ContractParty) 与多个项目(ContractProject)。

    现阶段与 ARProject.customer_name 文本字段【双轨并行】：历史数据由回填迁移按
    (合同名, 交付部门) 去重生成，旧字段保留不动，确保现有查询/导入/导出零影响。
    """
    contract_no = models.CharField('合同编号', max_length=50, blank=True, default='', db_index=True)
    name = models.CharField('合同名称', max_length=200, db_index=True)
    delivery_dept = models.CharField('交付部门', max_length=50, blank=True, default='', db_index=True)
    sign_date = models.DateField('签订日期', null=True, blank=True)
    amount = models.DecimalField('合同金额', max_digits=15, decimal_places=2, null=True, blank=True)
    notes = models.TextField('备注', blank=True, default='')
    customers = models.ManyToManyField(Customer, through='ContractParty', related_name='contracts')
    projects = models.ManyToManyField(ARProject, through='ContractProject', related_name='contracts')
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='created_contracts')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_contracts'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name', 'delivery_dept']),
        ]

    def _gen_contract_no(self):
        """生成合同编号：P-部门-日期-序号（如 P-YS-20260606-0001）。
        部门取项目编号同款部门简码；无对应简码时省略部门段（P-日期-序号）。"""
        dept_code = ARProject.DEPT_PROJECT_PREFIX.get(self.delivery_dept, '')
        mid = f'{dept_code}-' if dept_code else ''
        prefix = f'P-{mid}{datetime.date.today().strftime("%Y%m%d")}-'
        with transaction.atomic():
            existing = (Contract.objects.filter(contract_no__startswith=prefix)
                        .select_for_update().values_list('contract_no', flat=True))
            max_seq = -1
            for no in existing:
                try:
                    max_seq = max(max_seq, int(no.rsplit('-', 1)[-1]))
                except (ValueError, IndexError):
                    continue
            return f'{prefix}{max_seq + 1:04d}'

    def save(self, *args, **kwargs):
        # 未指定合同编号时自动生成 P-部门-日期-序号
        if not (self.contract_no or '').strip():
            self.contract_no = self._gen_contract_no()
        return super().save(*args, **kwargs)

    def to_dict(self, with_links=False):
        d = {
            'id': self.id,
            'contract_no': self.contract_no,
            'name': self.name,
            'delivery_dept': self.delivery_dept,
            'sign_date': str(self.sign_date) if self.sign_date else None,
            'amount': str(self.amount) if self.amount is not None else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if with_links:
            d['parties'] = [
                {'customer_id': pt.customer_id, 'customer_name': pt.customer.name,
                 'role': pt.role, 'share': str(pt.share) if pt.share is not None else None}
                for pt in self.parties.select_related('customer').all()
            ]
            d['projects'] = [
                {'project_id': cp.project_id, 'project_no': cp.project.project_no,
                 'short_name': cp.project.short_name, 'is_primary': cp.is_primary}
                for cp in self.project_links.select_related('project').all()
            ]
        else:
            d['party_count'] = self.parties.count()
            d['project_count'] = self.project_links.count()
        return d


class ContractParty(models.Model):
    """合同—客户 关联（多对多中间表）：一个合同可挂多个客户，可记主/次与分成比例。"""
    ROLE_CHOICES = [('main', '主客户'), ('sub', '次客户')]
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='parties')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='contract_links')
    role = models.CharField('角色', max_length=8, choices=ROLE_CHOICES, default='main')
    share = models.DecimalField('分成比例(%)', max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ar_contract_parties'
        unique_together = [('contract', 'customer')]
        ordering = ['contract', 'id']


class ContractProject(models.Model):
    """合同—项目 关联（多对多中间表）：一个合同对多个项目；一个项目也可挂多个合同。"""
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='project_links')
    project = models.ForeignKey(ARProject, on_delete=models.CASCADE, related_name='contract_links')
    is_primary = models.BooleanField('主合同', default=True,
                                     help_text='项目挂多个合同时，标记其主合同')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ar_contract_projects'
        unique_together = [('contract', 'project')]
        ordering = ['contract', 'id']


def _eomonth(year, month):
    """Return the last day of the given month as a date."""
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


def cycle_end_date(op_date, cycle_start_day=1):
    """运作日期所在「对账周期」的结束日。

    cycle_start_day=1（默认）即自然月：结束日 = 当月月末（与历史口径一致）。
    cycle_start_day=N（2~28）：账期月为每月N日~下月N-1日。运作日 >= N 落在
    本期（结束日=下月N-1），否则落在上期（结束日=本月N-1）。"""
    csd = int(cycle_start_day or 1)
    if csd <= 1:
        return _eomonth(op_date.year, op_date.month)
    if op_date.day >= csd:
        ny, nm = (op_date.year + 1, 1) if op_date.month == 12 else (op_date.year, op_date.month + 1)
        return datetime.date(ny, nm, csd - 1)
    return datetime.date(op_date.year, op_date.month, csd - 1)


def compute_record_due_date(project, op_date):
    """应收到期日 = 对账周期结束日 + 项目总账期天数。
    模型 save 与项目变更信号共用此函数，保证两处推算口径一致。"""
    anchor = cycle_end_date(op_date, getattr(project, 'cycle_start_day', 1))
    return anchor + datetime.timedelta(days=project.total_days)


def _as_date(v):
    """Coerce a value (date / datetime / ISO string / None) to a date, or None.

    The update/create views assign raw or normalized date *strings* to model
    instances before serialising, so date arithmetic must tolerate strings.
    """
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


class ARRecord(models.Model):
    """应收账款明细 — 每项目每月一条"""
    project = models.ForeignKey(ARProject, on_delete=models.CASCADE,
                                related_name='ar_records', db_index=True)
    # Denormalised for direct index on delivery_dept without JOIN
    delivery_dept = models.CharField('交付部门', max_length=50, db_index=True, blank=True, default='')
    operation_date = models.DateField('运作日期', db_index=True, null=True, blank=True,
                                      help_text='应收发生日期；历史年/月数据迁移为当月1日')
    # 派生列：始终与 operation_date 同步（save 时维护），供按年/月的聚合分析走索引
    operation_year = models.IntegerField('运作年', db_index=True)
    operation_month = models.IntegerField('运作月', db_index=True)
    estimated_amount = models.DecimalField('预估上账金额', max_digits=15, decimal_places=2, default=0)
    actual_invoice_amount = models.DecimalField('实际开票金额', max_digits=15, decimal_places=2,
                                                null=True, blank=True)
    tax_amount = models.DecimalField('税额', max_digits=15, decimal_places=2,
                                     null=True, blank=True)
    invoice_date = models.DateField('开票日期', null=True, blank=True, db_index=True)
    account_diff_adjustment = models.DecimalField('账实差额调整', max_digits=15,
                                                  decimal_places=2, default=0)
    outstanding_amount = models.DecimalField('未回款金额', max_digits=15, decimal_places=2, default=0)
    due_date = models.DateField('应收日期', db_index=True, null=True, blank=True)
    # 目标回款日期：业务手工填写的回款目标（非必填），与系统按账期推算的 due_date 并行
    target_collection_date = models.DateField('目标回款日期', null=True, blank=True, db_index=True)
    reconciliation_date = models.DateField('对账日期', null=True, blank=True, db_index=True)
    invoice_batch_no = models.CharField('开票批次号', max_length=50, blank=True, default='',
                                        db_index=True,
                                        help_text='合并开票批次号；相同批次号的记录将合并为一张发票')
    notes = models.TextField('备注', blank=True, default='')
    collector = models.CharField('催收负责人', max_length=100, blank=True, default='', db_index=True)
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='created_ar_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_records'
        ordering = ['-operation_date']
        indexes = [
            models.Index(fields=['delivery_dept', 'due_date']),
            models.Index(fields=['delivery_dept', 'operation_year', 'operation_month']),
            models.Index(fields=['operation_year', 'operation_month']),
            models.Index(fields=['due_date']),
            models.Index(fields=['outstanding_amount']),
            models.Index(fields=['invoice_date']),
            models.Index(fields=['reconciliation_date']),
            # 服务端排序新增列（大数据量下点表头排序走索引）
            models.Index(fields=['estimated_amount']),
            models.Index(fields=['actual_invoice_amount']),
            models.Index(fields=['created_at']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(outstanding_amount__gte=0),
                name='ar_record_outstanding_non_negative',
            ),
        ]

    def _compute_due_date(self):
        try:
            op = self.operation_date or datetime.date(self.operation_year, self.operation_month, 1)
            return compute_record_due_date(self.project, op)
        except Exception:
            return None

    def _compute_tax(self):
        if self.project.invoice_mode == '全额' and self.actual_invoice_amount:
            rate = self.project.tax_rate
            if rate:
                return (self.actual_invoice_amount / (1 + rate) * rate).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP)
        return self.tax_amount

    def recompute_derived(self, save=True):
        # 未收回金额口径：上账金额 + 调整额 - 回款金额
        base = self.estimated_amount or Decimal('0')
        total_paid = Decimal('0')
        if self.pk:
            total_paid = (self.payments.aggregate(s=Sum('amount'))['s'] or Decimal('0'))
        adj = self.account_diff_adjustment or Decimal('0')
        adjusted_base = base + adj
        outstanding = adjusted_base - total_paid
        if outstanding < Decimal('0'):
            # 带出真实算式，便于核对究竟是哪个值导致为负（预估/调整/累计回款）
            def _f(v):
                return f'{v:,.2f}'
            raise ValidationError(
                f'未收回金额不能为负：预估上账 {_f(base)} + 账实差额 {_f(adj)} '
                f'− 累计回款 {_f(total_paid)} = {_f(outstanding)}。'
                f'请核对预估上账金额或账实差额调整。'
            )
        self.outstanding_amount = outstanding
        self.tax_amount = self._compute_tax()
        if save:
            ARRecord.objects.filter(pk=self.pk).update(
                outstanding_amount=self.outstanding_amount,
                tax_amount=self.tax_amount,
            )

    def save(self, *args, **kwargs):
        # operation_date 为正源；年/月是派生列（兼容存量按年/月的聚合与筛选）。
        # 仅给年/月的旧调用方（含存量测试/脚本）反向推导为当月1日。
        if self.operation_date:
            self.operation_year = self.operation_date.year
            self.operation_month = self.operation_date.month
        elif self.operation_year and self.operation_month:
            self.operation_date = datetime.date(self.operation_year, self.operation_month, 1)
        self.delivery_dept = self.project.delivery_dept
        if not self.due_date:
            self.due_date = self._compute_due_date()
        self.recompute_derived(save=False)
        super().save(*args, **kwargs)

    # ── read-only properties (not stored) ──────────────────────────────────────
    def _recon_phase_status(self, today):
        """Reconciliation phase: 对账期内 vs 对账逾期（非销售/开票责任）。"""
        try:
            recon_days = self.project.reconciliation_days
            eom = _eomonth(self.operation_year, self.operation_month)
            recon_due = eom + datetime.timedelta(days=recon_days)
            if recon_days > 0 and today > recon_due:
                overdue = (today - recon_due).days
                return {'code': 'recon_overdue', 'label': f'对账逾期{overdue}天',
                        'style': 'warn'}
        except Exception:
            pass
        return {'code': 'in_recon_period', 'label': '对账期内', 'style': 'muted'}

    def post_invoice_status(self, today=None):
        """
        责任状态 — 跨应收全流程的责任归属判定。
        Returns dict: {code, label, style}  — style in {ok, blue, warn, danger, muted}

        责任链：对账逾期(非销售责任) → 开票逾期(开票人责任) → 票后/回款逾期(销售对接人责任)。
        不开票项目跳过开票环节，对账后直接进入回款责任。
        """
        today = today or datetime.date.today()
        outstanding = self.outstanding_amount or Decimal('0')
        inv_date = _as_date(self.invoice_date)
        recon_date = _as_date(self.reconciliation_date)
        post_days = self.project.post_invoice_days
        no_invoice = (self.project.invoice_type == '不开票')

        # Phase 0: Fully collected
        if outstanding <= 0:
            return {'code': 'settled', 'label': '已结清', 'style': 'ok'}

        # 不开票项目：无开票环节，对账后直接进入回款（销售对接人）责任
        if no_invoice:
            if recon_date:
                due = recon_date + datetime.timedelta(days=post_days)
                if today <= due:
                    remaining = (due - today).days
                    return {'code': 'collection_waiting', 'label': f'回款等待中 ({remaining}天)',
                            'style': 'blue'}
                overdue = (today - due).days
                return {'code': 'collection_overdue', 'label': f'回款逾期{overdue}天',
                        'style': 'danger'}
            return self._recon_phase_status(today)

        # Phase 1: Invoice issued — track post-invoice collection period（销售对接人责任）
        if inv_date:
            due = inv_date + datetime.timedelta(days=post_days)
            if today <= due:
                remaining = (due - today).days
                return {'code': 'post_invoice_waiting', 'label': f'票后等待中 ({remaining}天)',
                        'style': 'blue'}
            overdue = (today - due).days
            return {'code': 'post_invoice_overdue', 'label': f'票后逾期{overdue}天',
                    'style': 'danger'}

        # Phase 2: Reconciled but not yet invoiced — 开票人责任
        is_reconciled = (recon_date is not None
                         or self.actual_invoice_amount is not None)
        if is_reconciled:
            wait = self.project.invoice_wait_days
            if recon_date and wait > 0:
                invoice_due = recon_date + datetime.timedelta(days=wait)
                if today > invoice_due:
                    overdue = (today - invoice_due).days
                    return {'code': 'invoice_overdue', 'label': f'开票逾期{overdue}天',
                            'style': 'warn'}
            return {'code': 'pending_invoice', 'label': '待开票', 'style': 'blue'}

        # Phase 3: Not yet reconciled — check reconciliation deadline
        return self._recon_phase_status(today)

    @property
    def reconciliation_status(self):
        if (self.outstanding_amount or Decimal('0')) <= 0:
            return '已结清'
        # 业务规则：已开票默认视作已对账
        if self.actual_invoice_amount is not None:
            return '已对账'
        return '已对账' if self.reconciliation_date else '未对账'

    @property
    def invoice_status(self):
        if (self.outstanding_amount or Decimal('0')) <= 0:
            return '已结清'
        if not self.actual_invoice_amount:
            return '未开票'
        total_paid = self.payments.aggregate(s=Sum('amount'))['s'] or Decimal('0')
        if total_paid > 0:
            return '部分回款'
        return '已开票'

    def status_dict(self, today=None):
        today = today or datetime.date.today()
        eomonth_today = _eomonth(today.year, today.month)
        outstanding = self.outstanding_amount or Decimal('0')
        due = self.due_date
        is_overdue = bool(outstanding > 0 and due and due < today)
        overdue_days = (today - due).days if is_overdue else 0
        is_current = bool(outstanding > 0 and due and not is_overdue
                          and due <= eomonth_today)
        is_not_due = bool(outstanding > 0 and not is_overdue and not is_current)
        return {
            'is_overdue': is_overdue,
            'overdue_days': overdue_days,
            'is_current': is_current,
            'is_not_due': is_not_due,
        }

    def to_dict(self, today=None, include_payments=False):
        st = self.status_dict(today)
        d = {
            'id': self.id,
            'project_id': self.project_id,
            'project_no': self.project.project_no,
            'short_name': self.project.short_name,
            'customer_name': self.project.customer_name,
            'delivery_dept': self.delivery_dept,
            'project_manager': self.project.project_manager,
            'sales_contact': self.project.sales_contact,
            'total_days': self.project.total_days,
            'invoice_mode': self.project.invoice_mode,
            'tax_rate': str(self.project.tax_rate),
            'operation_date': str(self.operation_date) if self.operation_date else None,
            'operation_year': self.operation_year,
            'operation_month': self.operation_month,
            'estimated_amount': str(self.estimated_amount),
            'actual_invoice_amount': str(self.actual_invoice_amount) if self.actual_invoice_amount is not None else None,
            'tax_amount': str(self.tax_amount) if self.tax_amount is not None else None,
            'invoice_date': str(self.invoice_date) if self.invoice_date else None,
            'account_diff_adjustment': str(self.account_diff_adjustment),
            'outstanding_amount': str(self.outstanding_amount),
            'due_date': str(self.due_date) if self.due_date else None,
            'target_collection_date': str(self.target_collection_date) if self.target_collection_date else None,
            'reconciliation_date': str(self.reconciliation_date) if self.reconciliation_date else None,
            'reconciliation_status': self.reconciliation_status,
            'invoice_status': self.invoice_status,
            'post_invoice_status': self.post_invoice_status(today),
            'invoice_batch_no': self.invoice_batch_no,
            'notes': self.notes,
            'collector': self.collector,
            **st,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_payments:
            d['payments'] = [p.to_dict() for p in self.payments.order_by('payment_no')]
            d['adjustments'] = [a.to_dict() for a in self.adjustments.all()]
        return d


# 非现金回款来源：冲减应收未收，但不构成现金事件，现金流/资金池口径须排除。
NON_CASH_PAYMENT_SOURCES = ('预收抵扣', '内部往来')


class ARPayment(models.Model):
    """回款子表 — 每次回款一行，不限次数。

    source 区分现金回款与两类「非现金」冲减：
    - 预收抵扣：以客户预收款冲减应收，由预收核销自动生成；
    - 内部往来：事业部间内部往来核销，手工登记（日期/往来部门/金额，可多次）。
    二者都会冲减 outstanding（应收口径已收回），但**都不是新的现金事件**，故现金流/
    资金池统计须排除（见 NON_CASH_PAYMENT_SOURCES），避免重复计现金。
    """
    SOURCE_CHOICES = [('回款', '回款'), ('预收抵扣', '预收抵扣'), ('内部往来', '内部往来')]

    ar_record = models.ForeignKey(ARRecord, on_delete=models.CASCADE,
                                  related_name='payments', db_index=True)
    payment_no = models.IntegerField('回款序号')
    amount = models.DecimalField('回款金额', max_digits=15, decimal_places=2)
    payment_date = models.DateField('回款日期', db_index=True)
    source = models.CharField('回款来源', max_length=8, choices=SOURCE_CHOICES,
                              default='回款', db_index=True)
    # 内部往来核销专用：往来事业部（系统部门之一）。其它来源留空。
    counterparty_dept = models.CharField('往来部门', max_length=50, blank=True,
                                         default='', db_index=True)
    notes = models.TextField('备注', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ar_payments'
        unique_together = [('ar_record', 'payment_no')]
        ordering = ['ar_record', 'payment_no']
        indexes = [
            models.Index(fields=['ar_record', 'payment_date']),
            models.Index(fields=['payment_date']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'ar_record_id': self.ar_record_id,
            'payment_no': self.payment_no,
            'amount': str(self.amount),
            'payment_date': str(self.payment_date),
            'source': self.source,
            'counterparty_dept': self.counterparty_dept,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ARAdjustment(models.Model):
    """账实差额调整明细 — 一条应收可多次调整，每次各带原因与金额（可正可负）。

    ARRecord.account_diff_adjustment 退化为派生合计（信号自动同步），所有
    存量按合计的查询/导出/批次开票口径零改动；新链路以明细为正源，可追溯
    每笔差额因何而来（如：运费差、扣款、补付、四舍五入）。"""
    ar_record = models.ForeignKey(ARRecord, on_delete=models.CASCADE,
                                  related_name='adjustments', db_index=True)
    amount = models.DecimalField('调整金额', max_digits=15, decimal_places=2)
    reason = models.CharField('调整原因', max_length=200, blank=True, default='')
    adjust_date = models.DateField('调整日期', null=True, blank=True)
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='created_ar_adjustments')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ar_adjustments'
        ordering = ['ar_record', 'id']

    def to_dict(self):
        return {
            'id': self.id,
            'ar_record_id': self.ar_record_id,
            'amount': str(self.amount),
            'reason': self.reason,
            'adjust_date': str(self.adjust_date) if self.adjust_date else None,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# ── Budget models ──────────────────────────────────────────────────────────────

class CollectionBudget(models.Model):
    """收款预算"""
    project_no = models.CharField('项目编号', max_length=20, blank=True, default='', db_index=True)
    short_name = models.CharField('项目简称', max_length=200)
    expected_date = models.DateField('预计本月收款时间', db_index=True)
    sub_dept = models.CharField('二级部门', max_length=100, blank=True, default='')
    delivery_dept = models.CharField('交付部门', max_length=50, db_index=True, blank=True, default='')
    amount = models.DecimalField('金额', max_digits=15, decimal_places=2)
    notes = models.TextField('备注', blank=True, default='')
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='collection_budgets')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_collection_budgets'
        ordering = ['expected_date']
        indexes = [
            models.Index(fields=['delivery_dept', 'expected_date']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'project_no': self.project_no,
            'short_name': self.short_name,
            'expected_date': str(self.expected_date),
            'sub_dept': self.sub_dept,
            'delivery_dept': self.delivery_dept,
            'amount': str(self.amount),
            'notes': self.notes,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ARFilterScheme(models.Model):
    """筛选方案（对标金蝶云星空「过滤方案」）：把一组高级筛选条件命名保存，
    可设为私有（仅本人）或公共（团队共享）。conditions/match 为前端筛选 DSL 的快照。

    module 标识方案所属的列表（当前仅 ar_records），便于未来在别的台账复用。"""
    SCOPE_CHOICES = [('private', '私有'), ('public', '公共')]

    name = models.CharField('方案名称', max_length=40)
    module = models.CharField('所属列表', max_length=40, default='ar_records', db_index=True)
    scope = models.CharField('可见范围', max_length=10, choices=SCOPE_CHOICES,
                             default='private', db_index=True)
    conditions = models.TextField('条件快照(JSON)', blank=True, default='[]')
    match = models.CharField('组间连接', max_length=4, default='all')  # all(且) | any(或)
    owner = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                              null=True, blank=True, related_name='ar_filter_schemes')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_filter_schemes'
        ordering = ['name']
        indexes = [
            models.Index(fields=['module', 'scope']),
            models.Index(fields=['owner', 'module']),
        ]

    def to_dict(self):
        import json as _json
        try:
            conds = _json.loads(self.conditions or '[]')
        except (ValueError, TypeError):
            conds = []
        return {
            'id': self.id,
            'name': self.name,
            'module': self.module,
            'scope': self.scope,
            'conditions': conds,
            'match': self.match,
            'owner_id': self.owner_id,
            'owner_name': self.owner.name if self.owner else '',
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ARSchemeDefault(models.Model):
    """用户的「默认筛选方案」（按列表 module 唯一）：跟随账号、跨设备同步。
    方案删除时级联清理；可指向自己的私有方案或团队公共方案。"""
    user = models.ForeignKey(PaikuanUser, on_delete=models.CASCADE,
                             related_name='ar_scheme_defaults')
    module = models.CharField('所属列表', max_length=40, default='ar_records', db_index=True)
    scheme = models.ForeignKey(ARFilterScheme, on_delete=models.CASCADE,
                               related_name='default_of')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_scheme_defaults'
        unique_together = [('user', 'module')]


class AdvanceRecord(models.Model):
    """预收/预付台账明细 — 每笔预收或预付一条，direction 区分方向。

    预收：客户先付款给我们 → 现金流入；预付：我们先付供应商 → 现金流出。
    现金事件发生在 occur_date / advance_amount；后续随交付/收货通过
    AdvanceWriteoff 逐笔核销（冲减），核销为账务重分类、非现金事件。
    """
    DIRECTION_CHOICES = [('预收', '预收'), ('预付', '预付')]

    project = models.ForeignKey(ARProject, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='advance_records', db_index=True)
    # Denormalised: synced from project when linked; otherwise hand-entered.
    delivery_dept = models.CharField('交付部门', max_length=50, db_index=True, blank=True, default='')
    direction = models.CharField('方向', max_length=4, choices=DIRECTION_CHOICES, db_index=True)
    counterparty = models.CharField('往来单位', max_length=200, blank=True, default='')
    occur_year = models.IntegerField('发生年', db_index=True)
    occur_month = models.IntegerField('发生月', db_index=True)
    occur_date = models.DateField('款项日期', db_index=True, null=True, blank=True)
    advance_amount = models.DecimalField('预收/预付金额', max_digits=15, decimal_places=2, default=0)
    expected_writeoff_date = models.DateField('预计核销日期', null=True, blank=True, db_index=True)
    written_off_amount = models.DecimalField('已核销金额', max_digits=15, decimal_places=2, default=0)
    balance_amount = models.DecimalField('未核销余额', max_digits=15, decimal_places=2, default=0)
    notes = models.TextField('备注', blank=True, default='')
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='created_advance_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_advance_records'
        ordering = ['-occur_year', '-occur_month', '-occur_date']
        indexes = [
            models.Index(fields=['direction', 'delivery_dept']),
            models.Index(fields=['delivery_dept', 'occur_year', 'occur_month']),
            models.Index(fields=['occur_date']),
            models.Index(fields=['balance_amount']),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance_amount__gte=0),
                name='advance_balance_non_negative',
            ),
        ]

    def recompute_derived(self, save=True):
        """未核销余额口径：预收/预付金额 − 累计核销。"""
        base = self.advance_amount or Decimal('0')
        total_wo = Decimal('0')
        if self.pk:
            total_wo = self.writeoffs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
        balance = base - total_wo
        if balance < Decimal('0'):
            def _f(v):
                return f'{v:,.2f}'
            raise ValidationError(
                f'未核销余额不能为负：预收/预付金额 {_f(base)} − 累计核销 {_f(total_wo)} '
                f'= {_f(balance)}。请核对金额或核销记录。'
            )
        q = Decimal('0.01')
        self.written_off_amount = total_wo.quantize(q, rounding=ROUND_HALF_UP)
        self.balance_amount = balance.quantize(q, rounding=ROUND_HALF_UP)
        if save:
            AdvanceRecord.objects.filter(pk=self.pk).update(
                written_off_amount=self.written_off_amount,
                balance_amount=self.balance_amount,
            )

    def save(self, *args, **kwargs):
        if self.project_id:
            self.delivery_dept = self.project.delivery_dept
        self.recompute_derived(save=False)
        super().save(*args, **kwargs)

    @property
    def writeoff_status(self):
        if (self.balance_amount or Decimal('0')) <= 0:
            return '已核销'
        if (self.written_off_amount or Decimal('0')) > 0:
            return '部分核销'
        return '未核销'

    def aging_dict(self, today=None):
        """挂账账龄：未核销余额从款项日期起的挂账天数；超预计核销日期则逾期。"""
        today = today or datetime.date.today()
        if (self.balance_amount or Decimal('0')) <= 0:
            return {'pending_days': 0, 'is_overdue': False, 'overdue_days': 0}
        base_date = _as_date(self.occur_date)
        pending_days = (today - base_date).days if base_date else 0
        exp = _as_date(self.expected_writeoff_date)
        is_overdue = bool(exp and today > exp)
        overdue_days = (today - exp).days if is_overdue else 0
        return {'pending_days': pending_days, 'is_overdue': is_overdue,
                'overdue_days': overdue_days}

    def to_dict(self, today=None, include_writeoffs=False):
        ag = self.aging_dict(today)
        d = {
            'id': self.id,
            'project_id': self.project_id,
            'project_no': self.project.project_no if self.project_id else None,
            'short_name': self.project.short_name if self.project_id else None,
            'direction': self.direction,
            'counterparty': self.counterparty,
            'delivery_dept': self.delivery_dept,
            'occur_year': self.occur_year,
            'occur_month': self.occur_month,
            'occur_date': str(self.occur_date) if self.occur_date else None,
            'advance_amount': str(self.advance_amount),
            'expected_writeoff_date': str(self.expected_writeoff_date) if self.expected_writeoff_date else None,
            'written_off_amount': str(self.written_off_amount),
            'balance_amount': str(self.balance_amount),
            'writeoff_status': self.writeoff_status,
            'notes': self.notes,
            **ag,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_writeoffs:
            d['writeoffs'] = [w.to_dict() for w in self.writeoffs.order_by('writeoff_no')]
            d['installments'] = [i.to_dict() for i in self.installments.order_by('install_no')]
        return d


class AdvanceInstallment(models.Model):
    """预收/预付收付明细 — 一条预收/预付可多次到账/付出（与应收多次回款同构）。

    AdvanceRecord.advance_amount 退化为派生合计（信号自动同步 = 明细之和），
    所有按总额的查询/核销/资金池口径零改动；明细为正源，逐笔可追溯。"""
    advance_record = models.ForeignKey(AdvanceRecord, on_delete=models.CASCADE,
                                       related_name='installments', db_index=True)
    install_no = models.IntegerField('收付序号')
    amount = models.DecimalField('收付金额', max_digits=15, decimal_places=2)
    occur_date = models.DateField('收付日期', db_index=True)
    notes = models.TextField('备注', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ar_advance_installments'
        unique_together = [('advance_record', 'install_no')]
        ordering = ['advance_record', 'install_no']
        indexes = [
            models.Index(fields=['advance_record', 'occur_date']),
            models.Index(fields=['occur_date']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'advance_record_id': self.advance_record_id,
            'install_no': self.install_no,
            'amount': str(self.amount),
            'occur_date': str(self.occur_date),
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class BatchInvoiceEvent(models.Model):
    """批次开票事件 — 一个批次可多次开票（与批次回款同构）。

    每次开票一行：日期 + 价税合计金额 + 税额，按运作日期先进先出分摊到
    成员记录的「可开余额」（上账+差额−已开）；allocations 记录逐条分摊额，
    支持整次撤销。累计开票不得超过批次可开总额。"""
    batch_no = models.CharField('批次号', max_length=50, db_index=True)
    invoice_date = models.DateField('开票日期', db_index=True)
    amount = models.DecimalField('开票金额(价税合计)', max_digits=15, decimal_places=2)
    tax_amount = models.DecimalField('税额(差额模式手填)', max_digits=15, decimal_places=2,
                                     null=True, blank=True)
    notes = models.CharField('备注', max_length=200, blank=True, default='')
    allocations = models.JSONField('分摊明细', default=list)   # [{record_id, amount}]
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='created_batch_invoices')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ar_batch_invoice_events'
        ordering = ['batch_no', 'invoice_date', 'id']
        indexes = [models.Index(fields=['batch_no', 'invoice_date'])]

    def to_dict(self):
        return {
            'id': self.id,
            'batch_no': self.batch_no,
            'invoice_date': str(self.invoice_date),
            'amount': str(self.amount),
            'tax_amount': str(self.tax_amount) if self.tax_amount is not None else None,
            'notes': self.notes,
            'allocations': self.allocations,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AdvanceWriteoff(models.Model):
    """核销子表 — 每次核销一行，不限次数。

    预收核销可绑定一条应收明细 (ar_record) 并自动生成一笔「预收抵扣」回款
    (ar_payment) 冲减其 outstanding；删除本核销时该回款一并删除（应收余额恢复）。
    预付核销可绑定一条排款记录 (payment)，记录"哪笔排款用了此预付"。
    """
    advance_record = models.ForeignKey(AdvanceRecord, on_delete=models.CASCADE,
                                       related_name='writeoffs', db_index=True)
    writeoff_no = models.IntegerField('核销序号')
    amount = models.DecimalField('核销金额', max_digits=15, decimal_places=2)
    writeoff_date = models.DateField('核销日期', db_index=True)
    # 预收核销冲抵的应收明细及其生成的「预收抵扣」回款（仅预收方向、可选）
    ar_record = models.ForeignKey('ARRecord', on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name='advance_offsets')
    ar_payment = models.OneToOneField('ARPayment', on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='advance_writeoff')
    # 预付核销关联的排款记录（仅预付方向、可选）
    payment = models.ForeignKey('paikuan.Payment', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='prepaid_offsets')
    notes = models.TextField('备注', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ar_advance_writeoffs'
        unique_together = [('advance_record', 'writeoff_no')]
        ordering = ['advance_record', 'writeoff_no']
        indexes = [
            models.Index(fields=['advance_record', 'writeoff_date']),
            models.Index(fields=['writeoff_date']),
        ]
        constraints = [
            # 预付核销挂排款(payment) / 预收核销挂回款(ar_payment)，二者互斥；
            # 若同时存在，同一笔现金会在资金池里被重复计为流出
            models.CheckConstraint(
                name='writeoff_payment_xor_ar_payment',
                check=~(models.Q(payment__isnull=False) & models.Q(ar_payment__isnull=False)),
            ),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'advance_record_id': self.advance_record_id,
            'writeoff_no': self.writeoff_no,
            'amount': str(self.amount),
            'writeoff_date': str(self.writeoff_date),
            'ar_record_id': self.ar_record_id,
            'ar_payment_id': self.ar_payment_id,
            'ar_project_no': (self.ar_record.project.project_no
                              if self.ar_record_id and self.ar_record.project_id else None),
            'payment_id': self.payment_id,
            'payment_payee': (self.payment.payee[:60] if self.payment_id and self.payment else None),
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Supplier(models.Model):
    """供应商池 — 私有（绑项目）或公共（绑事业部）。

    排款录入时，收款方名称可模糊匹配到供应商，进而查询该供应商对应的预付未核销余额，
    并可在 PaymentModal 中直接发起核销（AdvanceWriteoff.payment 关联排款记录）实现闭环。
    """
    TYPE_CHOICES = [('private', '私有'), ('public', '公共')]

    name = models.CharField('供应商名称', max_length=200, db_index=True)
    supplier_type = models.CharField('类型', max_length=8, choices=TYPE_CHOICES,
                                     default='public', db_index=True)
    project = models.ForeignKey(ARProject, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='suppliers',
                                db_index=True)
    delivery_dept = models.CharField('交付部门', max_length=50, blank=True,
                                     default='', db_index=True)
    contact = models.CharField('联系人', max_length=100, blank=True, default='')
    notes = models.TextField('备注', blank=True, default='')
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True,
                                   related_name='created_suppliers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_suppliers'
        ordering = ['name']
        indexes = [
            models.Index(fields=['supplier_type', 'delivery_dept']),
        ]

    def save(self, *args, **kwargs):
        if self.project_id and self.supplier_type == 'private':
            self.delivery_dept = self.project.delivery_dept
        super().save(*args, **kwargs)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'supplier_type': self.supplier_type,
            'project_id': self.project_id,
            'project_no': self.project.project_no if self.project_id else None,
            'project_short_name': self.project.short_name if self.project_id else None,
            'delivery_dept': self.delivery_dept,
            'contact': self.contact,
            'notes': self.notes,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PaymentBudget(models.Model):
    """付款预算"""
    project_no = models.CharField('项目编号', max_length=20, blank=True, default='', db_index=True)
    short_name = models.CharField('项目简称/摘要', max_length=200)
    expected_date = models.DateField('预计本月付款时间', db_index=True)
    sub_dept = models.CharField('二级部门', max_length=100, blank=True, default='')
    delivery_dept = models.CharField('交付部门', max_length=50, db_index=True, blank=True, default='')
    amount = models.DecimalField('金额', max_digits=15, decimal_places=2)
    notes = models.TextField('备注', blank=True, default='')
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='payment_budgets')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_payment_budgets'
        ordering = ['expected_date']
        indexes = [
            models.Index(fields=['delivery_dept', 'expected_date']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'project_no': self.project_no,
            'short_name': self.short_name,
            'expected_date': str(self.expected_date),
            'sub_dept': self.sub_dept,
            'delivery_dept': self.delivery_dept,
            'amount': str(self.amount),
            'notes': self.notes,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ActionItem(models.Model):
    """P4 决策闭环 — 行动项，从今日信号自动生成，人工跟踪至关闭。"""
    STATUS_CHOICES = [
        ('open', '待处理'),
        ('in_progress', '处理中'),
        ('done', '已完成'),
        ('dismissed', '已忽略'),
    ]
    PRIORITY_CHOICES = [
        ('high', '高'),
        ('medium', '中'),
        ('low', '低'),
    ]

    title = models.CharField('标题', max_length=300)
    description = models.TextField('描述', blank=True, default='')
    bu = models.CharField('事业部', max_length=50, blank=True, default='', db_index=True)
    category = models.CharField('类型', max_length=50, blank=True, default='')
    priority = models.CharField('优先级', max_length=20, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    assignee = models.CharField('负责人', max_length=100, blank=True, default='')
    due_date = models.DateField('截止日期', null=True, blank=True)
    resolved_at = models.DateTimeField('完成时间', null=True, blank=True)
    source_signal = models.JSONField('来源信号', default=dict, blank=True)
    created_by = models.ForeignKey(PaikuanUser, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='created_action_items')
    resolved_by = models.ForeignKey(PaikuanUser, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='resolved_action_items')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_action_items'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'bu']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'bu': self.bu,
            'category': self.category,
            'priority': self.priority,
            'status': self.status,
            'assignee': self.assignee,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'source_signal': self.source_signal,
            'created_by': self.created_by.name if self.created_by_id else None,
            'resolved_by': self.resolved_by.name if self.resolved_by_id else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ── 资金池 (cash pool) ─────────────────────────────────────────────────────────

class CashPoolConfig(models.Model):
    """事业部资金池配置 — 超管手填期初基准；之后账面余额全部由收支流水推算（不存余额）。

    余额口径与现金流分析完全一致：
      流入 = 应收回款(剔除预收抵扣) + 预收款；
      流出 = 实付分期 − 预付核销冲抵 + 预付款；
      另加池间调拨（CashPoolTransfer，仅已生效的）。
    """
    delivery_dept = models.CharField('事业部', max_length=50, unique=True)
    initial_date = models.DateField('期初基准日', help_text='该日终的账面资金为期初值；之后的收支流水才计入余额')
    initial_amount = models.DecimalField('期初金额', max_digits=15, decimal_places=2, default=0)
    warning_days = models.IntegerField('预警窗口(天)', default=30,
                                       help_text='未设固定预警线时：资金预警线 = 未来N天刚性流出（已审批待付）')
    warning_amount = models.DecimalField('资金预警线(元)', max_digits=15, decimal_places=2,
                                         null=True, blank=True,
                                         help_text='手动设定的最低安全余额；设置后优先于按天数推算')
    notes = models.TextField('备注', blank=True, default='')
    updated_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='updated_pool_configs')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_cash_pool_configs'
        ordering = ['delivery_dept']

    def to_dict(self):
        return {
            'id': self.id,
            'delivery_dept': self.delivery_dept,
            'initial_date': str(self.initial_date),
            'initial_amount': str(self.initial_amount),
            'warning_days': self.warning_days,
            'warning_amount': str(self.warning_amount) if self.warning_amount is not None else None,
            'notes': self.notes,
            'updated_by_name': self.updated_by.name if self.updated_by else '',
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CashPoolTransfer(models.Model):
    """池间资金调拨（内部拆借）— 只挪不灭：集团合计余额恒等于各池之和。

    两阶段流程：事业部用户发起的调拨为「待审批」(pending)，须由调出方所在
    事业部（或超管）批准后才生效计入余额；超管直接调拨即时生效。
    余额推算只统计 status='approved' 的记录。
    """
    STATUS_CHOICES = [('pending', '待审批'), ('approved', '已生效'), ('rejected', '已拒绝')]

    from_dept = models.CharField('调出事业部', max_length=50, db_index=True)
    to_dept = models.CharField('调入事业部', max_length=50, db_index=True)
    amount = models.DecimalField('调拨金额', max_digits=15, decimal_places=2)
    transfer_date = models.DateField('调拨日期', db_index=True)
    expected_return_date = models.DateField('约定归还日', null=True, blank=True)
    notes = models.TextField('备注', blank=True, default='')
    status = models.CharField('状态', max_length=10, choices=STATUS_CHOICES,
                              default='approved', db_index=True)
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='created_pool_transfers')
    reviewed_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='reviewed_pool_transfers')
    reviewed_at = models.DateTimeField('审批时间', null=True, blank=True)
    review_notes = models.TextField('审批意见', blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ar_cash_pool_transfers'
        ordering = ['-transfer_date', '-id']

    def to_dict(self):
        return {
            'id': self.id,
            'from_dept': self.from_dept,
            'to_dept': self.to_dept,
            'amount': str(self.amount),
            'transfer_date': str(self.transfer_date),
            'expected_return_date': str(self.expected_return_date) if self.expected_return_date else None,
            'notes': self.notes,
            'status': self.status,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'reviewed_by_name': self.reviewed_by.name if self.reviewed_by else '',
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ARCollectionLog(models.Model):
    """催收跟进日志 — 每条应收账款可关联多条跟进记录（电话/邮件/拜访等）。"""
    LOG_TYPE_CHOICES = [
        ('call', '电话'),
        ('email', '邮件'),
        ('visit', '拜访'),
        ('meeting', '会议'),
        ('other', '其他'),
    ]
    STATUS_CHOICES = [
        ('pending', '待回复'),
        ('in_progress', '跟进中'),
        ('resolved', '已解决'),
        ('no_response', '无响应'),
    ]

    ar_record = models.ForeignKey(ARRecord, on_delete=models.CASCADE,
                                  related_name='collection_logs', db_index=True)
    log_type = models.CharField('跟进类型', max_length=10, choices=LOG_TYPE_CHOICES, default='call')
    contact_person = models.CharField('联系人', max_length=100, blank=True, default='')
    note = models.TextField('跟进内容', blank=True, default='')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='in_progress')
    follow_up_date = models.DateField('计划跟进日期', null=True, blank=True)
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='collection_logs')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_collection_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['ar_record', 'created_at']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'ar_record_id': self.ar_record_id,
            'log_type': self.log_type,
            'log_type_display': dict(self.LOG_TYPE_CHOICES).get(self.log_type, self.log_type),
            'contact_person': self.contact_person,
            'note': self.note,
            'status': self.status,
            'status_display': dict(self.STATUS_CHOICES).get(self.status, self.status),
            'follow_up_date': str(self.follow_up_date) if self.follow_up_date else None,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AgingBucketConfig(models.Model):
    """账龄分桶边界配置（全局单条，超管可改）。默认: 30/60/90 天。
    前端据此着色 + 账龄分析 Tab 按此切割区间。"""
    bucket1 = models.PositiveIntegerField('桶1上限(天)', default=30)
    bucket2 = models.PositiveIntegerField('桶2上限(天)', default=60)
    bucket3 = models.PositiveIntegerField('桶3上限(天)', default=90)
    updated_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='aging_config_updates')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_aging_bucket_config'

    @classmethod
    def get_or_default(cls):
        obj = cls.objects.first()
        if obj:
            return {'bucket1': obj.bucket1, 'bucket2': obj.bucket2, 'bucket3': obj.bucket3, 'id': obj.id}
        return {'bucket1': 30, 'bucket2': 60, 'bucket3': 90, 'id': None}

    def to_dict(self):
        return {
            'id': self.id,
            'bucket1': self.bucket1,
            'bucket2': self.bucket2,
            'bucket3': self.bucket3,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
