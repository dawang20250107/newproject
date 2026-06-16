from decimal import Decimal
from django.db import models
from django.contrib.auth.hashers import make_password, check_password


class PaikuanUser(models.Model):
    ROLE_CHOICES = [
        ('super_admin', '超级管理员'),
        ('manager', '经理'),
        ('operator', '操作员'),
        ('viewer', '查看员'),
    ]
    JOB_TITLE_CHOICES = [
        ('finance_director', '财务总监'),
        ('finance_bp', '财务BP'),
        ('chief_cashier', '总出纳'),
        ('cashier', '出纳'),
        ('general_manager', '总经理'),
        ('gm_assistant', '总经理助理'),
        ('settlement_accountant', '结算会计'),
    ]
    phone = models.CharField('手机号', max_length=15, unique=True)
    password_hash = models.CharField('密码哈希', max_length=256)
    name = models.CharField('姓名', max_length=50)
    role = models.CharField('角色', max_length=20, choices=ROLE_CHOICES, default='viewer')
    job_title = models.CharField('职务', max_length=30, choices=JOB_TITLE_CHOICES, blank=True, default='')
    departments = models.JSONField('负责部门', default=list)
    is_active = models.BooleanField('是否启用', default=True)
    is_approved = models.BooleanField('是否已审批', default=True)
    approved_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_users'
    )
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    # 改密时间戳：早于它签发的 JWT 一律拒绝（改密码即踢掉旧会话）
    pwd_changed_at = models.DateTimeField('密码修改时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'paikuan_users'
        verbose_name = '排款用户'

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)

    def to_dict(self):
        jt_map = dict(self.JOB_TITLE_CHOICES)
        return {
            'id': self.id,
            'phone': self.phone,
            'name': self.name,
            'role': self.role,
            'job_title': self.job_title,
            'job_title_label': jt_map.get(self.job_title, ''),
            'departments': self.departments,
            'is_active': self.is_active,
            'is_approved': self.is_approved,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Payment(models.Model):
    created_by = models.ForeignKey(
        PaikuanUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='payments'
    )
    updated_by = models.ForeignKey(
        PaikuanUser, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='updated_payments'
    )
    department = models.CharField('部门', max_length=100, db_index=True)
    applicant = models.CharField('申请人', max_length=100, blank=True, default='', db_index=True)
    approval_number = models.CharField('审批单号', max_length=100, blank=True, default='', db_index=True)
    # 关联项目台账编号（可选，自由填写不做强 FK）：用于排款时弹出该项目的预付余额，
    # 并按项目汇总已排/待付。历史存量行为空字符串。
    project_no = models.CharField('项目编号', max_length=20, blank=True, default='', db_index=True)
    # 二级部门/项目简称（选填，历史数据为空）。项目简称须与项目台账 short_name 匹配
    # 来源审批（静默唯一ID）：一条审批 ↔ 一条付款台账汇总记录，分批排款追加计划明细
    approval = models.ForeignKey('ApprovalRecord', on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='payments',
                                 verbose_name='来源审批')
    # （创建/编辑/导入时校验），作为排款与应收/现金流/分析/资金池打通的项目维度桥梁。
    secondary_dept = models.CharField('二级部门', max_length=100, blank=True, default='', db_index=True)
    project_short_name = models.CharField('项目简称', max_length=100, blank=True, default='', db_index=True)
    project_desc = models.TextField('付款事项描述')
    payee = models.CharField('收款方', max_length=200)
    total_amount = models.DecimalField('计划总金额', max_digits=15, decimal_places=2)
    planned_date = models.DateField('计划付款日期', db_index=True)
    notes = models.TextField('备注', blank=True, default='')
    plan_adjustment = models.DecimalField('计划调整金额', max_digits=15, decimal_places=2, null=True, blank=True)
    g7_number = models.CharField('G7编号', max_length=21, blank=True, default='', db_index=True)
    # 系统自动维护：等于所有关联 AdvanceWriteoff.amount 之和，现金流视图从 paid 中扣除此金额防双重计
    prepaid_offset_amount = models.DecimalField('预付核销冲抵金额', max_digits=15, decimal_places=2, default=Decimal('0'))
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'paikuan_payments'
        verbose_name = '排款记录'
        ordering = ['-planned_date', '-created_at']
        constraints = [
            # 业务唯一键：相同审批单号 + 部门 + 收款方 + 计划日期 + 计划金额
            # 视为重复排款。仅在 approval_number 非空时生效（占位 21 位 0 不算重复）。
            # 注意：MySQL 不支持条件唯一约束（partial unique index），Django 在
            # MySQL 上会静默跳过该约束（已用 SILENCED_SYSTEM_CHECKS=['models.W039']
            # 抑制 warning）。MySQL 生产下并发去重依赖应用层
            # _find_duplicate_payment + select_for_update；SQLite/PostgreSQL 走 DB 兜底。
            models.UniqueConstraint(
                fields=['department', 'approval_number', 'payee',
                        'planned_date', 'total_amount'],
                condition=~models.Q(approval_number=''),
                name='uniq_payment_business_key',
            ),
        ]

    @property
    def total_paid(self):
        try:
            return sum(i.pay_amount for i in self.installments.all())
        except Exception:
            return Decimal('0')

    def _effective_plan(self):
        return self.plan_adjustment if self.plan_adjustment is not None else self.total_amount

    @property
    def remaining(self):
        # 剩余应付 = 有效计划（调整额优先）− 已付 − 预付冲抵。
        # 预付冲抵的现金在预付时已流出，这里不再需要付现——与资金池刚性待付口径一致。
        covered = self.total_paid + (self.prepaid_offset_amount or Decimal('0'))
        return max(Decimal('0'), self._effective_plan() - covered)

    @property
    def status(self):
        covered = self.total_paid + (self.prepaid_offset_amount or Decimal('0'))
        plan = self._effective_plan()
        if covered >= plan:
            return 'settled'
        if self.plan_adjustment is not None:
            return 'adjusted'
        if covered > 0:
            return 'partial'
        return 'pending'

    def to_dict(self):
        insts = list(self.installments.all())
        plan_items = list(self.plan_items.all())
        total_paid_val = sum(i.pay_amount for i in insts)
        covered = total_paid_val + (self.prepaid_offset_amount or Decimal('0'))
        plan = self.plan_adjustment if self.plan_adjustment is not None else self.total_amount
        remaining_val = max(Decimal('0'), plan - covered)
        if covered >= plan:
            status_val = 'settled'
        elif self.plan_adjustment is not None:
            status_val = 'adjusted'
        elif covered > 0:
            status_val = 'partial'
        else:
            status_val = 'pending'
        return {
            'id': self.id,
            'department': self.department,
            'applicant': self.applicant,
            'approval_number': self.approval_number,
            'project_no': self.project_no,
            'approval_id': self.approval_id,
            'plan_count': len(plan_items),
            'plan_items': [
                {'id': pi.id, 'seq': pi.seq, 'planned_date': str(pi.planned_date),
                 'amount': str(pi.amount), 'notes': pi.notes}
                for pi in plan_items
            ],
            'secondary_dept': self.secondary_dept,
            'project_short_name': self.project_short_name,
            'project_desc': self.project_desc,
            'payee': self.payee,
            'total_amount': str(self.total_amount),
            'planned_date': str(self.planned_date) if self.planned_date else None,
            'installments': [
                {
                    'id': i.id,
                    'seq': i.seq,
                    'pay_date': str(i.pay_date),
                    'pay_amount': str(i.pay_amount),
                    'notes': i.notes,
                }
                for i in insts
            ],
            'notes': self.notes,
            'plan_adjustment': str(self.plan_adjustment) if self.plan_adjustment is not None else None,
            'g7_number': self.g7_number,
            'prepaid_offset_amount': str(self.prepaid_offset_amount),
            'total_paid': str(total_paid_val),
            'remaining': str(remaining_val),
            'status': status_val,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PaymentInstallment(models.Model):
    """付款明细子表：一条 Payment 可对应多次实际付款。"""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='installments')
    seq = models.PositiveSmallIntegerField('序号', default=0, db_index=True)
    pay_date = models.DateField('付款日期', db_index=True)
    pay_amount = models.DecimalField('付款金额', max_digits=15, decimal_places=2)
    notes = models.CharField('备注', max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'paikuan_payment_installments'
        verbose_name = '付款明细'
        ordering = ['seq', 'pay_date']
        constraints = [
            models.UniqueConstraint(fields=['payment', 'seq'],
                                    name='uniq_installment_seq_per_payment'),
        ]


class PaymentPlanItem(models.Model):
    """计划排款明细子表：一条 Payment（=一条审批的汇总）可分多批计划排款。

    Payment.total_amount = 明细金额之和、planned_date = 最早计划日（派生，
    写路径显式同步）；付款台账只显示一条汇总，点开看逐批计划与逐笔实付。"""
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='plan_items')
    seq = models.PositiveSmallIntegerField('批次序号', default=1, db_index=True)
    planned_date = models.DateField('计划日期', db_index=True)
    amount = models.DecimalField('计划金额', max_digits=15, decimal_places=2)
    notes = models.CharField('备注', max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'paikuan_payment_plan_items'
        ordering = ['payment', 'seq']
        indexes = [models.Index(fields=['payment', 'planned_date'])]


class ApprovalRecord(models.Model):
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '审批通过'),
        ('rejected', '已拒绝'),
        ('canceled', '已撤销'),
    ]
    applicant = models.CharField('申请人', max_length=100, db_index=True)
    department = models.CharField('所属事业部', max_length=100, db_index=True)
    # 二级部门/项目简称（选填，历史数据为空，可在操作栏补录）。
    # 项目简称须与项目台账 short_name 匹配（创建/编辑/导入时校验）。
    secondary_dept = models.CharField('二级部门', max_length=100, blank=True, default='', db_index=True)
    project_short_name = models.CharField('项目简称', max_length=100, blank=True, default='', db_index=True)
    approval_number = models.CharField('审批编号', max_length=21, db_index=True)
    g7_number = models.CharField('G7编号', max_length=21, blank=True, default='', db_index=True)
    summary = models.CharField('摘要', max_length=500)
    amount = models.DecimalField('申请金额', max_digits=15, decimal_places=2)
    # 分批排款累计：每次排款累加；排满申请金额自动归档（兼容一次性排款）
    scheduled_amount = models.DecimalField('已排款金额', max_digits=15, decimal_places=2, default=0)
    payee = models.CharField('收款主体', max_length=200)
    status = models.CharField('审批状态', max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    archived = models.BooleanField('是否归档', default=False, db_index=True)
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'paikuan_approval_records'
        ordering = ['-created_at']

    def to_dict(self):
        return {
            'id': self.id,
            'applicant': self.applicant,
            'department': self.department,
            'secondary_dept': self.secondary_dept,
            'project_short_name': self.project_short_name,
            'approval_number': self.approval_number,
            'g7_number': self.g7_number,
            'summary': self.summary,
            'amount': str(self.amount),
            'scheduled_amount': str(self.scheduled_amount or 0),
            'remaining_amount': str(max(Decimal('0'), (self.amount or Decimal('0'))
                                        - (self.scheduled_amount or Decimal('0')))),
            'payee': self.payee,
            'status': self.status,
            'archived': self.archived,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class JobPermission(models.Model):
    """Per-job-title permission config, managed by super_admin.

    config schema:
        {
          "pages":  {"dashboard": bool, "payments": bool, "stats": bool},
          "view":   {field_key: bool, ...},
          "edit":   {field_key: bool, ...},
          "can_create": bool,
          "can_delete": bool,
        }
    """
    job_title = models.CharField('职务', max_length=30, unique=True)
    config = models.JSONField('权限配置', default=dict)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'paikuan_job_permissions'
        verbose_name = '职务权限'


class PaymentChangeLog(models.Model):
    """Audit trail for Payment field changes (who/when/what changed)."""
    ACTION_CHOICES = [
        ('create', '新建'),
        ('update', '修改'),
        ('delete', '删除'),
    ]
    payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='change_logs'
    )
    payment_id_snapshot = models.IntegerField('排款ID快照', db_index=True)
    action = models.CharField('操作类型', max_length=10, choices=ACTION_CHOICES)
    operator = models.ForeignKey(
        PaikuanUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_changes'
    )
    operator_name = models.CharField('操作人姓名', max_length=100, blank=True, default='')
    field_name = models.CharField('字段名', max_length=50, blank=True, default='')
    field_label = models.CharField('字段中文名', max_length=50, blank=True, default='')
    old_value = models.TextField('修改前', blank=True, default='')
    new_value = models.TextField('修改后', blank=True, default='')
    at = models.DateTimeField('操作时间', auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'paikuan_payment_change_logs'
        verbose_name = '排款变更日志'
        ordering = ['-at']
        indexes = [
            models.Index(fields=['payment', 'at']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'payment_id': self.payment_id_snapshot,
            'action': self.action,
            'operator_id': self.operator_id,
            'operator_name': self.operator_name,
            'field_name': self.field_name,
            'field_label': self.field_label,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'at': self.at.isoformat() if self.at else None,
        }


class AuditLog(models.Model):
    """全系统操作审计 — 由 AuditLogMiddleware 自动记录所有 API 写操作。

    与 PaymentChangeLog（排款字段级变更）互补：这里是请求级轨迹（谁、何时、
    对哪个接口做了什么写操作、参数是什么、结果如何），覆盖应收/客户/预收/
    财务/权限等全部模块，用于审计追溯与异常排查。
    """
    user = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                             null=True, blank=True, related_name='audit_logs')
    user_name = models.CharField('操作人', max_length=100, blank=True, default='', db_index=True)
    method = models.CharField('方法', max_length=8)
    path = models.CharField('接口路径', max_length=300, db_index=True)
    module = models.CharField('模块', max_length=20, blank=True, default='', db_index=True)
    status_code = models.IntegerField('响应状态码', default=0)
    payload = models.JSONField('请求参数（已脱敏）', default=dict, blank=True)
    ip = models.CharField('来源IP', max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'paikuan_audit_logs'
        verbose_name = '操作审计日志'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user_name', 'created_at']),
            models.Index(fields=['module', 'created_at']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.user_name,
            'method': self.method,
            'path': self.path,
            'module': self.module,
            'status_code': self.status_code,
            'payload': self.payload,
            'ip': self.ip,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
