from django.db import models


class UserProfile(models.Model):
    """小程序用户档案（按 openid 索引）"""
    openid = models.CharField('微信openid', max_length=100, unique=True, db_index=True)
    display_name = models.CharField('微信昵称', max_length=100, blank=True, default='')
    dept = models.CharField('部门', max_length=100, blank=True, default='')
    role = models.CharField('岗位', max_length=100, blank=True, default='')
    name = models.CharField('姓名', max_length=100, blank=True, default='')
    avatar = models.TextField('头像(base64或URL)', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'mp_users'
        verbose_name = '小程序用户'
        verbose_name_plural = '小程序用户'

    def __str__(self):
        return self.name or self.display_name or self.openid[:8]


class DailyReport(models.Model):
    """日报记录（每用户每日唯一）"""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='reports')
    date = models.DateField('日期')
    blocks = models.JSONField('时段任务', default=list)
    works = models.TextField('行得通的是', blank=True, default='')
    not_works = models.TextField('行不通的是', blank=True, default='')
    plans = models.TextField('明日计划', blank=True, default='')
    commit_text = models.CharField('结语', max_length=500, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'mp_daily_reports'
        verbose_name = '日报'
        verbose_name_plural = '日报'
        unique_together = ('user', 'date')
        ordering = ['-date']

    def __str__(self):
        return f'{self.user} - {self.date}'
