# -*- coding: utf-8 -*-
"""Django model for payment_registrations (付款登记表)"""
# Models for 付款登记表 - to be placed in erp/models.py

PAYMENT_REGISTRATION_MODEL = '''
class PaymentRegistration(models.Model):
    """付款登记表 - 报销付款申请记录"""
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

    # 报销统计表扩展字段
    expense_category = models.CharField('报销类别', max_length=100, null=True, blank=True)
    expense_summary = models.DecimalField('报销金额', max_digits=12, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_registrations'
        ordering = ['-planned_date']
        verbose_name = '付款登记'
        verbose_name_plural = '付款登记'

    def __str__(self):
        return f"{self.applicant_name} - {self.project_name} - {self.pending_amount}"
'''
