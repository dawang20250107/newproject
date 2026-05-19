from django.db import models


class Payable(models.Model):
    """未回款记录（对接云开发 unpaid_records 表）"""
    STATUS_CHOICES = [
        ('abnormal', '异常'),
        ('normal', '正常'),
    ]

    class Meta:
        db_table = 'unpaid_records'
        ordering = ['-record_date']
        verbose_name = '未回款记录'
        verbose_name_plural = '未回款记录'

    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.DO_NOTHING,
        related_name='payables',
        null=True, blank=True,
    )
    project_name = models.CharField('项目名称', max_length=200, default='')
    manager_name = models.CharField('项目经理', max_length=100, default='')
    abnormal_amount = models.DecimalField('异常金额', max_digits=14, decimal_places=2, default=0)
    received_amount = models.DecimalField('已收金额', max_digits=14, decimal_places=2, default=0)
    unpaid_amount = models.DecimalField('未收金额', max_digits=14, decimal_places=2, default=0)
    days_overdue = models.IntegerField('逾期天数', default=0)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='normal')
    record_date = models.DateField('记录日期', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    def __str__(self):
        return f"{self.project_name} - {self.unpaid_amount}元"


class PaymentRegistration(models.Model):
    """付款登记表（已审批未付 / 报销统计表）"""
    # Sheet1: 已审批未付
    applicant_name = models.CharField('申请人', max_length=100, null=True, blank=True)
    invoice_no = models.CharField('票据号', max_length=100, null=True, blank=True)
    description = models.CharField('摘要', max_length=500, null=True, blank=True)
    project_name = models.CharField('项目', max_length=200, null=True, blank=True)
    planned_date = models.DateField('计划付款日期', null=True, blank=True)
    apply_amount = models.DecimalField('申请金额', max_digits=12, decimal_places=2, null=True, blank=True)
    paid_amount = models.DecimalField('已付金额', max_digits=12, decimal_places=2, null=True, blank=True)
    pending_amount = models.DecimalField('待付金额', max_digits=12, decimal_places=2, null=True, blank=True)
    pay_date = models.DateField('实际付款日期', null=True, blank=True)
    is_paid = models.BooleanField('是否已付款', default=False)
    payment_manager = models.CharField('付款负责人', max_length=100, null=True, blank=True)
    has_invoice = models.BooleanField('有无发票', default=False)
    # Sheet2 扩展字段
    expense_summary = models.DecimalField('报销金额', max_digits=12, decimal_places=2, null=True, blank=True)
    # 来源sheet标识
    source_sheet = models.CharField('来源Sheet', max_length=50, default='已审批未付')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_registrations'
        ordering = ['-planned_date']
        verbose_name = '付款登记'
        verbose_name_plural = '付款登记'

    def __str__(self):
        return f"{self.applicant_name} - {self.project_name} - {self.pending_amount}"
