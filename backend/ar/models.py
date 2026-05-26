import calendar
import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.db.models import Sum

from paikuan.models import PaikuanUser


class ARProject(models.Model):
    """项目主表 — 每个合同/项目一行"""
    project_no = models.CharField('项目编号', max_length=20, unique=True, db_index=True)
    contract_name = models.CharField('合同名称', max_length=200)
    short_name = models.CharField('项目简称', max_length=100, blank=True, default='')
    delivery_dept = models.CharField('交付部门', max_length=50, db_index=True)
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
    settlement_wait_days = models.IntegerField('结算等待期(天)', default=0)
    total_days = models.IntegerField('总账期(天)', default=0)
    invoice_mode = models.CharField('开票模式', max_length=4,
                                    choices=[('全额', '全额'), ('差额', '差额')], default='全额')
    invoice_type = models.CharField('专票/普票', max_length=4,
                                    choices=[('专票', '专票'), ('普票', '普票')], blank=True, default='')
    tax_rate = models.DecimalField('税率', max_digits=6, decimal_places=4, default=Decimal('0'))
    notes = models.TextField('备注', blank=True, default='')
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

    PROJECT_NO_START_SEQ = 1
    DEPT_PREFIX_MAP = {
        '集团总部': 'JT',
        '劳务事业部': 'LW',
        '运输事业部': 'YS',
        '自营事业部': 'ZY',
        '阔展事业部': 'KZ',
        '多式联运事业部': 'DS',
        '供应链事业部': 'GY',
    }

    def _project_no_prefix(self):
        dept_prefix = self.DEPT_PREFIX_MAP.get(self.delivery_dept, 'OT')
        return f'{dept_prefix}-{datetime.date.today().year}-'

    def _gen_project_no(self):
        prefix = self._project_no_prefix()
        with transaction.atomic():
            last = (ARProject.objects.filter(project_no__startswith=prefix)
                    .order_by('-project_no').first())
            seq = self.PROJECT_NO_START_SEQ
            if last:
                try:
                    seq = int(last.project_no.rsplit('-', 1)[-1]) + 1
                except ValueError:
                    seq = self.PROJECT_NO_START_SEQ
            return f'{prefix}{seq:04d}'

    def save(self, *args, **kwargs):
        if not self.project_no:
            self.project_no = self._gen_project_no()
        self.is_shared = (self.sales_contact != self.project_manager)
        self.total_days = (self.reconciliation_days + self.invoice_wait_days
                           + self.settlement_wait_days)
        super().save(*args, **kwargs)

    def to_dict(self):
        return {
            'id': self.id,
            'project_no': self.project_no,
            'contract_name': self.contract_name,
            'short_name': self.short_name,
            'delivery_dept': self.delivery_dept,
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
            'settlement_wait_days': self.settlement_wait_days,
            'total_days': self.total_days,
            'invoice_mode': self.invoice_mode,
            'invoice_type': self.invoice_type,
            'tax_rate': str(self.tax_rate),
            'notes': self.notes,
            'created_by_id': self.created_by_id,
            'created_by_name': self.created_by.name if self.created_by else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


def _eomonth(year, month):
    """Return the last day of the given month as a date."""
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


class ARRecord(models.Model):
    """应收账款明细 — 每项目每月一条"""
    project = models.ForeignKey(ARProject, on_delete=models.CASCADE,
                                related_name='ar_records', db_index=True)
    # Denormalised for direct index on delivery_dept without JOIN
    delivery_dept = models.CharField('交付部门', max_length=50, db_index=True, blank=True, default='')
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
    reconciliation_time = models.DateTimeField('对账时间', null=True, blank=True, db_index=True)
    notes = models.TextField('备注', blank=True, default='')
    created_by = models.ForeignKey(PaikuanUser, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='created_ar_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ar_records'
        unique_together = [('project', 'operation_year', 'operation_month')]
        ordering = ['-operation_year', '-operation_month']
        indexes = [
            models.Index(fields=['delivery_dept', 'due_date']),
            models.Index(fields=['delivery_dept', 'operation_year', 'operation_month']),
            models.Index(fields=['due_date']),
            models.Index(fields=['outstanding_amount']),
            models.Index(fields=['invoice_date']),
            models.Index(fields=['reconciliation_time']),
        ]

    def _compute_due_date(self):
        try:
            end_of_month = _eomonth(self.operation_year, self.operation_month)
            return end_of_month + datetime.timedelta(days=self.project.total_days)
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
        base = self.actual_invoice_amount if self.actual_invoice_amount is not None else self.estimated_amount
        total_paid = Decimal('0')
        if self.pk:
            total_paid = (self.payments.aggregate(s=Sum('amount'))['s'] or Decimal('0'))
        self.outstanding_amount = base - total_paid
        self.account_diff_adjustment = (
            (self.actual_invoice_amount or Decimal('0')) - self.estimated_amount
        )
        self.tax_amount = self._compute_tax()
        if save:
            ARRecord.objects.filter(pk=self.pk).update(
                outstanding_amount=self.outstanding_amount,
                account_diff_adjustment=self.account_diff_adjustment,
                tax_amount=self.tax_amount,
            )

    def save(self, *args, **kwargs):
        self.delivery_dept = self.project.delivery_dept
        if not self.due_date:
            self.due_date = self._compute_due_date()
        self.recompute_derived(save=False)
        super().save(*args, **kwargs)

    # ── read-only properties (not stored) ──────────────────────────────────────
    @property
    def reconciliation_status(self):
        return '已对账' if self.reconciliation_time else '未对账'

    @property
    def invoice_status(self):
        if not self.actual_invoice_amount:
            return '未开票'
        if self.outstanding_amount <= 0:
            return '已结清'
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
            'contract_name': self.project.contract_name,
            'delivery_dept': self.delivery_dept,
            'project_manager': self.project.project_manager,
            'sales_contact': self.project.sales_contact,
            'total_days': self.project.total_days,
            'invoice_mode': self.project.invoice_mode,
            'tax_rate': str(self.project.tax_rate),
            'operation_year': self.operation_year,
            'operation_month': self.operation_month,
            'estimated_amount': str(self.estimated_amount),
            'actual_invoice_amount': str(self.actual_invoice_amount) if self.actual_invoice_amount is not None else None,
            'tax_amount': str(self.tax_amount) if self.tax_amount is not None else None,
            'invoice_date': str(self.invoice_date) if self.invoice_date else None,
            'account_diff_adjustment': str(self.account_diff_adjustment),
            'outstanding_amount': str(self.outstanding_amount),
            'due_date': str(self.due_date) if self.due_date else None,
            'reconciliation_time': self.reconciliation_time.isoformat() if self.reconciliation_time else None,
            'reconciliation_status': self.reconciliation_status,
            'invoice_status': self.invoice_status,
            'notes': self.notes,
            **st,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_payments:
            d['payments'] = [p.to_dict() for p in self.payments.order_by('payment_no')]
        return d


class ARPayment(models.Model):
    """回款子表 — 每次回款一行，不限次数"""
    ar_record = models.ForeignKey(ARRecord, on_delete=models.CASCADE,
                                  related_name='payments', db_index=True)
    payment_no = models.IntegerField('回款序号')
    amount = models.DecimalField('回款金额', max_digits=15, decimal_places=2)
    payment_date = models.DateField('回款日期', db_index=True)
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
            'notes': self.notes,
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
