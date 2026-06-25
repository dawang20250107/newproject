from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('caiwu', '0002_l1_calculated_sign_l3_kingdee'),
    ]

    operations = [
        migrations.CreateModel(
            name='CaiwuJobPermission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job_title', models.CharField(max_length=30, unique=True, verbose_name='职务')),
                ('config', models.JSONField(default=dict, verbose_name='权限配置')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '职务权限',
                'db_table': 'caiwu_job_permissions',
            },
        ),
    ]
