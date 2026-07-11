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


class CockpitKnowledge(models.Model):
    """业财融合 Agent 的经营知识库：用户沉淀或 AI 提炼的经营洞察 / 背景 / 口径规则，
    作为后续对话的长期记忆，让助手越用越懂业务、判断可延续、可积累。"""
    KIND_CHOICES = [('insight', '洞察'), ('background', '背景'), ('rule', '口径/规则')]
    scope = models.CharField('范围', max_length=50, default='全集团', db_index=True)  # 事业部名 或 '全集团'
    kind = models.CharField('类型', max_length=20, default='insight')
    title = models.CharField('标题', max_length=120, blank=True, default='')
    content = models.TextField('内容')
    source = models.CharField('来源', max_length=10, default='user')  # user | ai
    pinned = models.BooleanField('置顶', default=False)
    created_by = models.ForeignKey('paikuan.PaikuanUser', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='cockpit_knowledge')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_cockpit_knowledge'
        ordering = ['-pinned', '-created_at']
        indexes = [models.Index(fields=['scope'])]

    def to_dict(self):
        return {
            'id': self.id,
            'scope': self.scope,
            'kind': self.kind,
            'title': self.title,
            'content': self.content,
            'source': self.source,
            'pinned': self.pinned,
            'created_by': self.created_by.name if self.created_by_id else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class CockpitChat(models.Model):
    """业财融合助手的对话留存：每个账号一条，保存其当前对话消息数组（JSON），
    实现跨设备按账号同步——刷新/换电脑不丢，直到用户主动清空。
    仅存精简后的消息（role/content/toolSteps/fb），不含流式中间态。"""
    user = models.OneToOneField('paikuan.PaikuanUser', on_delete=models.CASCADE,
                                related_name='cockpit_chat')
    messages = models.JSONField('对话消息', default=list, blank=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_cockpit_chat'


class InternalBatch(models.Model):
    """内部往来核对：一次上传 = 某记账主体（事业部/总部）某期间的金蝶内往明细。
    同 (主体, 年, 月) 重复上传时整体替换，保证期间数据幂等。"""
    business_unit = models.CharField('记账主体', max_length=32, db_index=True)
    year = models.IntegerField('年')
    month = models.IntegerField('月')
    kind = models.CharField('数据类型', max_length=10, default='detail')  # detail=明细分类账 / balance=核算维度余额表
    filename = models.CharField('文件名', max_length=200, blank=True, default='')
    row_count = models.IntegerField('明细行数', default=0)
    uploaded_by = models.CharField('上传人', max_length=64, blank=True, default='')
    created_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_internal_batch'
        indexes = [models.Index(fields=['year', 'month'])]

    def to_dict(self):
        return {
            'id': self.id, 'business_unit': self.business_unit,
            'year': self.year, 'month': self.month, 'kind': self.kind,
            'filename': self.filename, 'row_count': self.row_count,
            'uploaded_by': self.uploaded_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class InternalEntry(models.Model):
    """内部往来明细行（来自金蝶核算维度明细账，核算维度=往来单位）。
    side 由科目性质推导：资产类(1xxx，应收侧)借增；负债类(2xxx，应付侧)贷增。
    signed = 我方对对方的净头寸贡献（应收为正、应付为负），镜像核对时
    A 对 B 的 signed 合计 + B 对 A 的 signed 合计 应为 0。"""
    batch = models.ForeignKey(InternalBatch, on_delete=models.CASCADE, related_name='entries')
    business_unit = models.CharField('记账主体', max_length=32, db_index=True)
    counterparty = models.CharField('对方主体', max_length=32, blank=True, default='', db_index=True)  # 映射后的 BU；空=未识别
    counterparty_raw = models.CharField('对方原文', max_length=200, blank=True, default='')
    year = models.IntegerField('年')
    month = models.IntegerField('月')
    biz_date = models.DateField('日期', null=True, blank=True)
    voucher_no = models.CharField('凭证字号', max_length=64, blank=True, default='')
    subject_code = models.CharField('科目编码', max_length=32, blank=True, default='')
    subject_name = models.CharField('科目名称', max_length=100, blank=True, default='')
    summary = models.CharField('摘要', max_length=300, blank=True, default='')
    debit = models.DecimalField('借方', max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField('贷方', max_digits=18, decimal_places=2, default=0)
    side = models.CharField('方向', max_length=4, default='ar')  # ar=应收侧 / ap=应付侧

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_internal_entry'
        indexes = [models.Index(fields=['business_unit', 'counterparty', 'year', 'month'])]

    @property
    def signed(self):
        """对对方的净头寸贡献（债权为正）：借-贷 对两类科目均成立——
        资产类借增（应收 +）；负债类贷增（应付贷方 → 债权 −）。"""
        return (self.debit or 0) - (self.credit or 0)

    def to_dict(self):
        return {
            'id': self.id, 'business_unit': self.business_unit,
            'counterparty': self.counterparty, 'counterparty_raw': self.counterparty_raw,
            'date': self.biz_date.isoformat() if self.biz_date else '',
            'voucher_no': self.voucher_no,
            'subject_code': self.subject_code, 'subject_name': self.subject_name,
            'summary': self.summary,
            'debit': float(self.debit or 0), 'credit': float(self.credit or 0),
            'side': self.side, 'signed': float(self.signed),
        }


class InternalBalance(models.Model):
    """内部往来余额行（来自金蝶「核算维度余额表」，组织机构 × 账簿）。
    余额口径核对含期初遗留差异，是矩阵层的首选口径；signed 均为 借-贷（债权为正）。"""
    batch = models.ForeignKey(InternalBatch, on_delete=models.CASCADE, related_name='balances')
    business_unit = models.CharField('记账主体', max_length=32, db_index=True)
    counterparty = models.CharField('对方主体', max_length=32, blank=True, default='', db_index=True)
    counterparty_raw = models.CharField('对方原文', max_length=200, blank=True, default='')
    year = models.IntegerField('年')
    month = models.IntegerField('月')
    subject_code = models.CharField('科目编码', max_length=32, blank=True, default='')
    subject_name = models.CharField('科目名称', max_length=100, blank=True, default='')
    opening = models.DecimalField('期初(借-贷)', max_digits=18, decimal_places=2, default=0)
    debit = models.DecimalField('本期借方', max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField('本期贷方', max_digits=18, decimal_places=2, default=0)
    closing = models.DecimalField('期末(借-贷)', max_digits=18, decimal_places=2, default=0)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_internal_balance'
        indexes = [models.Index(fields=['business_unit', 'counterparty', 'year', 'month'])]

    def to_dict(self):
        return {
            'id': self.id, 'business_unit': self.business_unit,
            'counterparty': self.counterparty, 'counterparty_raw': self.counterparty_raw,
            'subject_code': self.subject_code, 'subject_name': self.subject_name,
            'opening': float(self.opening or 0),
            'debit': float(self.debit or 0), 'credit': float(self.credit or 0),
            'closing': float(self.closing or 0),
        }


class AiFeedback(models.Model):
    """AI 助手回答的用户评价（👍/👎），沉淀为改进素材与评测样本。"""
    user = models.ForeignKey('paikuan.PaikuanUser', null=True, blank=True,
                             on_delete=models.SET_NULL, related_name='ai_feedback')
    rating = models.SmallIntegerField('评价')            # 1=👍 / -1=👎
    question = models.TextField('用户提问', blank=True, default='')
    answer = models.TextField('AI 回答', blank=True, default='')
    comment = models.CharField('补充说明', max_length=300, blank=True, default='')
    scope = models.CharField('分析范围', max_length=32, blank=True, default='')
    year = models.IntegerField('年', null=True, blank=True)
    month = models.IntegerField('月', null=True, blank=True)
    created_at = models.DateTimeField('时间', auto_now_add=True)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_ai_feedback'
        ordering = ['-created_at']


class AiUsage(models.Model):
    """AI 用量计量（按 日×用途×模型 聚合行，表恒小）：token 成本可控的数据基座。"""
    date = models.DateField('日期', db_index=True)
    kind = models.CharField('用途', max_length=20, default='other')   # chat/report/analysis/chart/distill/research/other
    model = models.CharField('模型', max_length=40, blank=True, default='')
    prompt_tokens = models.BigIntegerField('输入tokens', default=0)
    completion_tokens = models.BigIntegerField('输出tokens', default=0)
    calls = models.IntegerField('调用次数', default=0)

    class Meta:
        app_label = 'caiwu'
        db_table = 'caiwu_ai_usage'
        unique_together = [('date', 'kind', 'model')]


class CloseChecklistNote(models.Model):
    """月末关账清单逐项批注（d7）：对某年月某检查项标记 负责人 + 处理说明 + 本月已确认。
    warn/todo 项常是「已知晓、本月接受」的状态，标记后已确认项灰显，月末例会当走查单用。"""
    year = models.PositiveIntegerField('年')
    month = models.PositiveIntegerField('月')
    item_key = models.CharField('检查项 key', max_length=64)
    owner = models.CharField('负责人', max_length=100, blank=True, default='')
    note = models.CharField('处理说明', max_length=500, blank=True, default='')
    confirmed = models.BooleanField('本月已确认', default=False)
    updated_by = models.ForeignKey('paikuan.PaikuanUser', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='close_checklist_notes')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'caiwu_close_checklist_note'
        unique_together = ('year', 'month', 'item_key')

    def to_dict(self):
        return {'owner': self.owner, 'note': self.note, 'confirmed': self.confirmed,
                'updated_by': self.updated_by.name if self.updated_by else None,
                'updated_at': self.updated_at.isoformat() if self.updated_at else None}
