from django.contrib.auth.models import User
from django.db import models


class Project(models.Model):
    """项目基础信息"""
    project_name = models.CharField('项目名称', max_length=200, blank=True, default='')
    project_code = models.CharField('项目编号', max_length=50, blank=True, default='')
    customer_name = models.CharField('客户名称', max_length=200, blank=True, default='')
    manager_name = models.CharField('负责人', max_length=100, blank=True, default='')
    contract_amount = models.DecimalField('合同金额', max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    business_model = models.CharField('业务模式', max_length=100, blank=True, default='')
    department = models.CharField('部门', max_length=100, blank=True, default='')
    sales_contact = models.CharField('销售对接人', max_length=100, blank=True, default='')
    shared_type = models.CharField('共享/独有', max_length=50, blank=True, default='')
    settlement_cycle = models.CharField('结算周期', max_length=50, blank=True, default='')
    total_zhangqi = models.CharField('总账期', max_length=50, blank=True, default='')

    class Meta:
        db_table = 'projects'
        verbose_name = '项目'
        verbose_name_plural = '项目'

    def __str__(self):
        return self.project_name or f'Project {self.id}'


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    openid = models.CharField(max_length=100, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        db_table = 'user_profiles'
        verbose_name = '用户档案'
        verbose_name_plural = '用户档案'

    def __str__(self):
        if self.user:
            return self.user.username
        return f'openid:{self.openid[:8] if self.openid else "?"}'


class DailyReport(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='reports')
    date = models.DateField('日期')
    blocks = models.JSONField('时段数据', default=list)
    works = models.TextField('行得通的是', blank=True, default='')
    not_works = models.TextField('行不通的是', blank=True, default='')
    plans = models.TextField('明日计划', blank=True, default='')
    commit_text = models.CharField('结语', max_length=500, blank=True, default='')
    dept = models.CharField('部门', max_length=100, blank=True, default='')
    role = models.CharField('岗位', max_length=100, blank=True, default='')
    name = models.CharField('姓名', max_length=100, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'daily_reports'
        verbose_name = '日报'
        verbose_name_plural = '日报'
        unique_together = ('user', 'date')
        ordering = ['-date']

    def __str__(self):
        return f'{self.user} - {self.date}'


class ReceivableData(models.Model):
    """应收款数据源（mp_receivable_data，38行来自Excel）"""
    STATUS_CHOICES = [
        ('normal', '正常'),
        ('abnormal', '异常'),
        ('pending', '待处理'),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE,
        related_name='receivable_records',
        null=True, blank=True
    )
    project_name = models.CharField('项目名称', max_length=200, blank=True, default='')
    manager_name = models.CharField('负责人', max_length=100, blank=True, default='')
    month = models.CharField('月份', max_length=7, blank=True, default='')  # YYYY-MM
    receivable_amount = models.DecimalField('应收金额', max_digits=15, decimal_places=2, default=0)
    received_amount = models.DecimalField('已回款金额', max_digits=15, decimal_places=2, default=0)
    unpaid_amount = models.DecimalField('未收款金额', max_digits=15, decimal_places=2, default=0)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='normal')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    is_billed = models.CharField('是否开票', max_length=20, blank=True, default='')
    is_overdue = models.CharField('是否逾期', max_length=20, blank=True, default='')
    shared_type = models.CharField('共享/独有', max_length=50, blank=True, default='')
    contract_zhangqi = models.CharField('合同账期', max_length=50, blank=True, default='')
    execute_zhangqi = models.CharField('执行账期', max_length=50, blank=True, default='')
    total_zhangqi = models.CharField('总账期', max_length=50, blank=True, default='')

    class Meta:
        db_table = 'receivable_data'
        verbose_name = '应收款数据'
        verbose_name_plural = '应收款数据'
        ordering = ['-month']


class UnpaidRecord(models.Model):
    """未回款记录（核心数据表）"""
    STATUS_CHOICES = [
        ('normal', '正常'),
        ('abnormal', '异常'),
        ('overdue', '逾期'),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE,
        related_name='unpaid_records',
        null=True, blank=True
    )
    project_name = models.CharField('项目名称', max_length=200, blank=True, default='')
    manager_name = models.CharField('负责人', max_length=100, blank=True, default='')
    abnormal_amount = models.DecimalField('异常金额', max_digits=15, decimal_places=2, default=0)
    received_amount = models.DecimalField('已回款金额', max_digits=15, decimal_places=2, default=0)
    unpaid_amount = models.DecimalField('未收款金额', max_digits=15, decimal_places=2, default=0)
    days_overdue = models.IntegerField('逾期天数', default=0)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='normal')
    record_date = models.DateField('记录日期', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'unpaid_records'
        verbose_name = '未回款记录'
        verbose_name_plural = '未回款记录'
        ordering = ['-abnormal_amount']

    def __str__(self):
        return f'{self.project_name} - {self.abnormal_amount}'


class PaymentRegistration(models.Model):
    """付款登记表（报销统计表）"""
    applicant_name = models.CharField('申请人', max_length=100, blank=True, default='')
    invoice_no = models.CharField('钉钉编号', max_length=100, blank=True, default='')
    description = models.CharField('说明', max_length=500, blank=True, default='')
    project_name = models.CharField('项目名称', max_length=200, blank=True, default='')
    planned_date = models.DateField('计划日期', null=True, blank=True)
    apply_amount = models.DecimalField('申请金额', max_digits=15, decimal_places=2, default=0)
    paid_amount = models.DecimalField('已付金额', max_digits=15, decimal_places=2, default=0)
    pending_amount = models.DecimalField('待付金额', max_digits=15, decimal_places=2, default=0)
    pay_date = models.DateField('付款日期', null=True, blank=True)
    is_paid = models.BooleanField('是否已付', default=False)
    payment_manager = models.CharField('付款经理', max_length=100, blank=True, default='')
    has_invoice = models.BooleanField('有无专票', default=False)
    expense_summary = models.CharField('费用摘要', max_length=500, blank=True, default='')
    source_sheet = models.CharField('来源Sheet', max_length=100, blank=True, default='')
    dingtalk_no = models.CharField('钉钉编号2', max_length=100, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'payment_registrations'
        verbose_name = '付款登记'
        verbose_name_plural = '付款登记'
        ordering = ['-id']
