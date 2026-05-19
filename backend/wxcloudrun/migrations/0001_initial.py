from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('openid', models.CharField(db_index=True, max_length=100, unique=True, verbose_name='微信openid')),
                ('display_name', models.CharField(blank=True, default='', max_length=100, verbose_name='微信昵称')),
                ('dept', models.CharField(blank=True, default='', max_length=100, verbose_name='部门')),
                ('role', models.CharField(blank=True, default='', max_length=100, verbose_name='岗位')),
                ('name', models.CharField(blank=True, default='', max_length=100, verbose_name='姓名')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '小程序用户',
                'verbose_name_plural': '小程序用户',
                'db_table': 'mp_users',
            },
        ),
        migrations.CreateModel(
            name='DailyReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='日期')),
                ('blocks', models.JSONField(default=list, verbose_name='时段任务')),
                ('works', models.TextField(blank=True, default='', verbose_name='行得通的是')),
                ('not_works', models.TextField(blank=True, default='', verbose_name='行不通的是')),
                ('plans', models.TextField(blank=True, default='', verbose_name='明日计划')),
                ('commit_text', models.CharField(blank=True, default='', max_length=500, verbose_name='结语')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='reports',
                    to='wxcloudrun.userprofile',
                )),
            ],
            options={
                'verbose_name': '日报',
                'verbose_name_plural': '日报',
                'db_table': 'mp_daily_reports',
                'ordering': ['-date'],
                'unique_together': {('user', 'date')},
            },
        ),
    ]
