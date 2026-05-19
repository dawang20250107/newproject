from django.db import models


class Project(models.Model):
    """项目基础信息（对接云开发 projects 表）"""

    class Meta:
        db_table = 'projects'
        ordering = ['-id']
        verbose_name = '项目'
        verbose_name_plural = '项目'

    project_name = models.CharField('项目名称', max_length=200)
    project_code = models.CharField('项目编号', max_length=50, unique=True)
    customer_name = models.CharField('客户名称', max_length=200)
    manager_name = models.CharField('项目经理', max_length=100)
    contract_amount = models.DecimalField('合同金额', max_digits=15, decimal_places=2, default=0)
    business_model = models.CharField('业务模式', max_length=50, blank=True, default='')
    department = models.CharField('项目部门', max_length=100, blank=True, default='')
    sales_contact = models.CharField('销售对接人', max_length=100, blank=True, default='')
    shared_type = models.CharField('共享/独有', max_length=20, blank=True, default='')
    settlement_cycle = models.CharField('结算周期', max_length=20, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    def __str__(self):
        return f"{self.project_name} ({self.project_code})"
