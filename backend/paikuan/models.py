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
    approval_number = models.CharField('审批单号', max_length=100, blank=True, default='', db_index=True)
    project_desc = models.TextField('付款事项描述')
    payee = models.CharField('收款方', max_length=200)
    total_amount = models.DecimalField('计划总金额', max_digits=15, decimal_places=2)
    planned_date = models.DateField('计划付款日期', db_index=True)
    pay1_date = models.DateField('第1次付款日期', null=True, blank=True)
    pay1_amount = models.DecimalField('第1次付款金额', max_digits=15, decimal_places=2, default=0)
    pay2_date = models.DateField('第2次付款日期', null=True, blank=True)
    pay2_amount = models.DecimalField('第2次付款金额', max_digits=15, decimal_places=2, default=0)
    pay3_date = models.DateField('第3次付款日期', null=True, blank=True)
    pay3_amount = models.DecimalField('第3次付款金额', max_digits=15, decimal_places=2, default=0)
    notes = models.TextField('备注', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'paikuan_payments'
        verbose_name = '排款记录'
        ordering = ['-planned_date', '-created_at']

    @property
    def total_paid(self):
        return (
            (self.pay1_amount or Decimal('0')) +
            (self.pay2_amount or Decimal('0')) +
            (self.pay3_amount or Decimal('0'))
        )

    @property
    def remaining(self):
        return self.total_amount - self.total_paid

    @property
    def status(self):
        paid = self.total_paid
        if paid >= self.total_amount:
            return 'settled'
        elif paid > 0:
            return 'partial'
        return 'pending'

    def to_dict(self):
        return {
            'id': self.id,
            'department': self.department,
            'approval_number': self.approval_number,
            'project_desc': self.project_desc,
            'payee': self.payee,
            'total_amount': str(self.total_amount),
            'planned_date': str(self.planned_date) if self.planned_date else None,
            'pay1_date': str(self.pay1_date) if self.pay1_date else None,
            'pay1_amount': str(self.pay1_amount),
            'pay2_date': str(self.pay2_date) if self.pay2_date else None,
            'pay2_amount': str(self.pay2_amount),
            'pay3_date': str(self.pay3_date) if self.pay3_date else None,
            'pay3_amount': str(self.pay3_amount),
            'notes': self.notes,
            'total_paid': str(self.total_paid),
            'remaining': str(self.remaining),
            'status': self.status,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ApprovalRecord(models.Model):
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '审批通过'),
        ('rejected', '已拒绝'),
        ('canceled', '已撤销'),
    ]
    applicant = models.CharField('申请人', max_length=100, db_index=True)
    department = models.CharField('所属事业部', max_length=100, db_index=True)
    approval_number = models.CharField('审批编号', max_length=21, db_index=True)
    summary = models.CharField('摘要', max_length=500)
    amount = models.DecimalField('申请金额', max_digits=15, decimal_places=2)
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
            'approval_number': self.approval_number,
            'summary': self.summary,
            'amount': str(self.amount),
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
