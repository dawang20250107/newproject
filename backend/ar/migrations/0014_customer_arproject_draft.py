import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0013_arrecord_invoice_batch_no'),
    ]

    operations = [
        migrations.CreateModel(
            name='Customer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(db_index=True, max_length=200, unique=True, verbose_name='客户名称')),
                ('level', models.CharField(blank=True, default='', max_length=50, verbose_name='客户等级')),
                ('contact', models.CharField(blank=True, default='', max_length=200, verbose_name='联系人')),
                ('notes', models.TextField(blank=True, default='', verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'ar_customers', 'ordering': ['name']},
        ),
        migrations.AddField(
            model_name='arproject',
            name='is_draft',
            field=models.BooleanField(
                db_index=True, default=False,
                help_text='导入时自动创建的未完善项目；补齐信息后置为 False',
                verbose_name='草稿/待完善',
            ),
        ),
        migrations.AddField(
            model_name='arproject',
            name='customer',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='projects',
                to='ar.customer',
                verbose_name='关联客户',
            ),
        ),
    ]
