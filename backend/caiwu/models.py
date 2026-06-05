from django.db import models
from django.contrib.auth.hashers import make_password, check_password

BUSINESS_UNITS = [
    '集团总部', '劳务事业部', '运输事业部', '自营事业部',
    '阔展事业部', '多式联运事业部', '供应链事业部',
]
VALID_BUSINESS_UNITS = set(BUSINESS_UNITS)

ROLES = ['super_admin', 'manager', 'operator', 'viewer', 'general_manager']

JOB_TITLES = {
    'finance_director': '财务总监',
    'finance_bp': '财务BP',
    'general_manager': '总经理',
}

# Roles that can see all business units regardless of departments assignment
ALL_BU_ROLES = {'super_admin', 'manager', 'general_manager'}


class CaiwuUser(models.Model):
    phone = models.CharField('手机号', max_length=15, unique=True, db_index=True)
    password_hash = models.CharField('密码哈希', max_length=256)
    name = models.CharField('姓名', max_length=50)
    role = models.CharField('角色', max_length=20, default='viewer')
    job_title = models.CharField('职务', max_length=30, blank=True, default='')
    departments = models.JSONField('负责事业部', default=list)
    is_active = models.BooleanField('是否启用', default=True)
    is_approved = models.BooleanField('是否已审批', default=False)
    approved_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='approved_users',
    )
    approved_at = models.DateTimeField('审批时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_user'

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password_hash)

    def to_dict(self):
        return {
            'id': self.id,
            'phone': self.phone,
            'name': self.name,
            'role': self.role,
            'job_title': self.job_title,
            'departments': self.departments,
            'is_active': self.is_active,
            'is_approved': self.is_approved,
            'approved_by_name': self.approved_by.name if self.approved_by_id else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class L1Category(models.Model):
    name = models.CharField('科目名称', max_length=100, unique=True)
    sort_order = models.IntegerField('排序', default=0)
    is_profit_driver = models.BooleanField('利润驱动因素（瀑布图用）', default=False)
    is_calculated = models.BooleanField(
        '计算行', default=False,
        help_text='计算行不接受导入数据，由报表自动推算（如运营毛利、经营净利）',
    )
    sign = models.IntegerField(
        '利润方向', default=1,
        help_text='收入类填 1，成本/费用类填 -1，用于瀑布图方向判断',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_l1category'
        ordering = ['sort_order', 'id']

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sort_order': self.sort_order,
            'is_profit_driver': self.is_profit_driver,
            'is_calculated': self.is_calculated,
            'sign': self.sign,
        }


class L2Category(models.Model):
    business_unit = models.CharField('事业部', max_length=50, db_index=True)
    name = models.CharField('项目部名称', max_length=100)
    sort_order = models.IntegerField('排序', default=0)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_l2category'
        ordering = ['sort_order', 'id']
        unique_together = [('business_unit', 'name')]

    def to_dict(self):
        return {
            'id': self.id,
            'business_unit': self.business_unit,
            'name': self.name,
            'sort_order': self.sort_order,
        }


class L3Category(models.Model):
    business_unit = models.CharField('事业部', max_length=50, db_index=True)
    l1_category = models.ForeignKey(
        L1Category, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='l3_categories',
    )
    name = models.CharField('科目明细', max_length=200)
    sort_order = models.IntegerField('排序', default=0)
    kingdee_code = models.CharField(
        '金蝶科目编码', max_length=50, blank=True, default='',
        help_text='如 6001.03.01，用于金蝶明细账直接导入时的科目匹配',
    )

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_l3category'
        ordering = ['sort_order', 'id']
        unique_together = [('business_unit', 'l1_category', 'name')]

    def to_dict(self):
        return {
            'id': self.id,
            'business_unit': self.business_unit,
            'l1_category_id': self.l1_category_id,
            'l1_name': self.l1_category.name if self.l1_category_id else None,
            'name': self.name,
            'sort_order': self.sort_order,
            'kingdee_code': self.kingdee_code,
        }


class ImportBatch(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'

    # Each BU+month requires TWO source tables:
    #  'department_detail': Kingdee 部门明细表 (main data source)
    #  'profit_loss':       手工利润表 (reconciliation reference)
    TYPE_DEPT = 'department_detail'
    TYPE_PL = 'profit_loss'

    business_unit = models.CharField('事业部', max_length=50, db_index=True)
    year = models.IntegerField('年份')
    month = models.IntegerField('月份')
    batch_type = models.CharField('表类型', max_length=30, default=TYPE_DEPT)
    status = models.CharField('状态', max_length=20, default=STATUS_DRAFT)
    # Uploader is a unified platform account (Stage 2+3). The legacy CaiwuUser
    # table is retained for history but no longer referenced by live records.
    uploaded_by = models.ForeignKey(
        'paikuan.PaikuanUser', null=True, on_delete=models.SET_NULL,
        related_name='caiwu_batches',
    )
    uploaded_at = models.DateTimeField('上传时间', auto_now_add=True)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)
    row_count = models.IntegerField('数据行数', default=0)
    file_name = models.CharField('原文件名', max_length=255, blank=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_importbatch'
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['business_unit', 'year', 'month', 'status']),
            models.Index(fields=['year', 'month', 'status']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'business_unit': self.business_unit,
            'year': self.year,
            'month': self.month,
            'batch_type': self.batch_type,
            'status': self.status,
            'uploaded_by': self.uploaded_by.name if self.uploaded_by_id else None,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'row_count': self.row_count,
            'file_name': self.file_name,
        }


class FinancialEntry(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name='entries')
    l1 = models.ForeignKey(L1Category, on_delete=models.PROTECT, related_name='entries')
    l2 = models.ForeignKey(
        L2Category, null=True, blank=True, on_delete=models.SET_NULL, related_name='entries',
    )
    l3 = models.ForeignKey(
        L3Category, null=True, blank=True, on_delete=models.SET_NULL, related_name='entries',
    )
    amount = models.DecimalField('金额', max_digits=15, decimal_places=2)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_financialentry'
        indexes = [
            models.Index(fields=['batch', 'l1']),
            models.Index(fields=['batch', 'l1', 'l2']),
        ]


class FinancialTarget(models.Model):
    """Manually-entered revenue/profit targets per business unit per period.

    `month == 0` is the annual target for the year; `month` 1–12 are monthly
    targets. Achievement is computed by the views against the aggregated,
    published 部门明细表 actuals:
      target_revenue     ↔ 主营业务收入
      target_profit      ↔ 经营净利   (DB column keeps original name for compat)
      target_gross_profit↔ 经营毛利
    """
    MONTH_ANNUAL = 0

    business_unit = models.CharField('事业部', max_length=50, db_index=True)
    year = models.IntegerField('年份')
    month = models.IntegerField('月份', default=MONTH_ANNUAL, help_text='0=年度目标，1-12=当月目标')
    target_revenue = models.DecimalField('目标收入', max_digits=15, decimal_places=2, default=0)
    target_profit = models.DecimalField('经营净利目标', max_digits=15, decimal_places=2, default=0)
    target_gross_profit = models.DecimalField('经营毛利目标', max_digits=15, decimal_places=2, default=0)
    # Cross-db reference to the unified platform account (mirrors ImportBatch.uploaded_by).
    updated_by = models.ForeignKey(
        'paikuan.PaikuanUser', null=True, on_delete=models.SET_NULL,
        related_name='caiwu_targets',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_financial_target'
        ordering = ['business_unit', 'year', 'month']
        unique_together = [('business_unit', 'year', 'month')]
        indexes = [
            models.Index(fields=['year', 'month']),
        ]

    def to_dict(self):
        return {
            'id': self.id,
            'business_unit': self.business_unit,
            'year': self.year,
            'month': self.month,
            'target_revenue': float(self.target_revenue),
            'target_profit': float(self.target_profit),
            'target_gross_profit': float(self.target_gross_profit),
            'updated_by': self.updated_by.name if self.updated_by_id else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CaiwuJobPermission(models.Model):
    """Per-job-title granular permission config, managed by super_admin.

    config schema:
        {
          "pages":      {"report": bool, "data": bool, "charts": bool},
          "view":       {field_key: bool, ...},
          "can_upload": bool,
          "can_publish": bool,
          "can_delete": bool,
        }
    """
    job_title = models.CharField('职务', max_length=30, unique=True)
    config = models.JSONField('权限配置', default=dict)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_job_permissions'
        verbose_name = '职务权限'


class ProjectMargin(models.Model):
    """项目毛利：金蝶「核算维度明细账（按项目）」按项目汇总的收入/成本/费用。
    每个 (事业部, 年, 月, 项目名称) 一行，导入同期间时整体替换。
    收入 = 6001/6051 主营/其他业务收入(贷-借)；成本 = 6401/6402 主营业务成本(借-贷)；
    销售费用 = 6601(借-贷)；管理费用 = 6602(借-贷)。「无/空」项目名为未挂项目池。"""
    business_unit = models.CharField('事业部', max_length=50, db_index=True)
    year = models.IntegerField('年', db_index=True)
    month = models.IntegerField('月', db_index=True)
    project_name = models.CharField('项目名称', max_length=200, db_index=True)
    revenue = models.DecimalField('收入', max_digits=16, decimal_places=2, default=0)
    cost = models.DecimalField('主营成本', max_digits=16, decimal_places=2, default=0)
    sales_exp = models.DecimalField('销售费用', max_digits=16, decimal_places=2, default=0)
    mgmt_exp = models.DecimalField('管理费用', max_digits=16, decimal_places=2, default=0)
    uploaded_by = models.ForeignKey('paikuan.PaikuanUser', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='uploaded_project_margins')
    uploaded_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_project_margin'
        ordering = ['business_unit', 'year', 'month', 'project_name']
        indexes = [
            models.Index(fields=['business_unit', 'year', 'month']),
        ]

    def to_dict(self):
        rev, cost = float(self.revenue), float(self.cost)
        margin = rev - cost
        return {
            'id': self.id,
            'project_name': self.project_name,
            'revenue': rev,
            'cost': cost,
            'sales_exp': float(self.sales_exp),
            'mgmt_exp': float(self.mgmt_exp),
            'margin': margin,
            'margin_rate': round(margin / rev * 100, 1) if rev else None,
        }
