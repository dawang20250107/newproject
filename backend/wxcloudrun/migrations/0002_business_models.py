from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('wxcloudrun', '0001_add_userprofile_dailyreport'),
    ]

    operations = [
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('project_name', models.CharField(blank=True, default='', max_length=200, verbose_name='项目名称')),
                ('project_code', models.CharField(blank=True, default='', max_length=50, verbose_name='项目编号')),
                ('customer_name', models.CharField(blank=True, default='', max_length=200, verbose_name='客户名称')),
                ('manager_name', models.CharField(blank=True, default='', max_length=100, verbose_name='负责人')),
                ('contract_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='合同金额')),
                ('business_model', models.CharField(blank=True, default='', max_length=100, verbose_name='业务模式')),
                ('department', models.CharField(blank=True, default='', max_length=100, verbose_name='部门')),
                ('sales_contact', models.CharField(blank=True, default='', max_length=100, verbose_name='销售对接人')),
                ('shared_type', models.CharField(blank=True, default='', max_length=50, verbose_name='共享/独有')),
                ('settlement_cycle', models.CharField(blank=True, default='', max_length=50, verbose_name='结算周期')),
                ('total_zhangqi', models.CharField(blank=True, default='', max_length=50, verbose_name='总账期')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
            ],
            options={
                'verbose_name': '项目',
                'verbose_name_plural': '项目',
                'db_table': 'projects',
            },
        ),
        migrations.CreateModel(
            name='ReceivableData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('project', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='receivable_records',
                    to='wxcloudrun.project',
                )),
                ('project_name', models.CharField(blank=True, default='', max_length=200, verbose_name='项目名称')),
                ('manager_name', models.CharField(blank=True, default='', max_length=100, verbose_name='负责人')),
                ('month', models.CharField(blank=True, default='', max_length=7, verbose_name='月份')),
                ('receivable_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='应收金额')),
                ('received_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='已回款金额')),
                ('unpaid_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='未收款金额')),
                ('status', models.CharField(
                    choices=[('normal', '正常'), ('abnormal', '异常'), ('pending', '待处理')],
                    default='normal', max_length=20, verbose_name='状态',
                )),
                ('is_billed', models.CharField(blank=True, default='', max_length=20, verbose_name='是否开票')),
                ('is_overdue', models.CharField(blank=True, default='', max_length=20, verbose_name='是否逾期')),
                ('shared_type', models.CharField(blank=True, default='', max_length=50, verbose_name='共享/独有')),
                ('contract_zhangqi', models.CharField(blank=True, default='', max_length=50, verbose_name='合同账期')),
                ('execute_zhangqi', models.CharField(blank=True, default='', max_length=50, verbose_name='执行账期')),
                ('total_zhangqi', models.CharField(blank=True, default='', max_length=50, verbose_name='总账期')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
            ],
            options={
                'verbose_name': '应收款数据',
                'verbose_name_plural': '应收款数据',
                'db_table': 'receivable_data',
                'ordering': ['-month'],
            },
        ),
        migrations.CreateModel(
            name='UnpaidRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('project', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='unpaid_records',
                    to='wxcloudrun.project',
                )),
                ('project_name', models.CharField(blank=True, default='', max_length=200, verbose_name='项目名称')),
                ('manager_name', models.CharField(blank=True, default='', max_length=100, verbose_name='负责人')),
                ('abnormal_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='异常金额')),
                ('received_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='已回款金额')),
                ('unpaid_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='未收款金额')),
                ('days_overdue', models.IntegerField(default=0, verbose_name='逾期天数')),
                ('status', models.CharField(
                    choices=[('normal', '正常'), ('abnormal', '异常'), ('overdue', '逾期')],
                    default='normal', max_length=20, verbose_name='状态',
                )),
                ('record_date', models.DateField(blank=True, null=True, verbose_name='记录日期')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
            ],
            options={
                'verbose_name': '未回款记录',
                'verbose_name_plural': '未回款记录',
                'db_table': 'unpaid_records',
                'ordering': ['-abnormal_amount'],
            },
        ),
        migrations.CreateModel(
            name='PaymentRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('applicant_name', models.CharField(blank=True, default='', max_length=100, verbose_name='申请人')),
                ('invoice_no', models.CharField(blank=True, default='', max_length=100, verbose_name='钉钉编号')),
                ('description', models.CharField(blank=True, default='', max_length=500, verbose_name='说明')),
                ('project_name', models.CharField(blank=True, default='', max_length=200, verbose_name='项目名称')),
                ('planned_date', models.DateField(blank=True, null=True, verbose_name='计划日期')),
                ('apply_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='申请金额')),
                ('paid_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='已付金额')),
                ('pending_amount', models.DecimalField(decimal_places=2, default=0, max_digits=15, verbose_name='待付金额')),
                ('pay_date', models.DateField(blank=True, null=True, verbose_name='付款日期')),
                ('is_paid', models.BooleanField(default=False, verbose_name='是否已付')),
                ('payment_manager', models.CharField(blank=True, default='', max_length=100, verbose_name='付款经理')),
                ('has_invoice', models.BooleanField(default=False, verbose_name='有无专票')),
                ('expense_summary', models.CharField(blank=True, default='', max_length=500, verbose_name='费用摘要')),
                ('source_sheet', models.CharField(blank=True, default='', max_length=100, verbose_name='来源Sheet')),
                ('dingtalk_no', models.CharField(blank=True, default='', max_length=100, verbose_name='钉钉编号2')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
            ],
            options={
                'verbose_name': '付款登记',
                'verbose_name_plural': '付款登记',
                'db_table': 'payment_registrations',
                'ordering': ['-id'],
            },
        ),
    ]
