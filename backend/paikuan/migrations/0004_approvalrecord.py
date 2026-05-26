from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('paikuan', '0003_jobpermission_alter_paikuanuser_job_title'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApprovalRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('applicant', models.CharField(db_index=True, max_length=100, verbose_name='申请人')),
                ('department', models.CharField(db_index=True, max_length=100, verbose_name='所属事业部')),
                ('approval_number', models.CharField(db_index=True, max_length=21, verbose_name='审批编号')),
                ('summary', models.CharField(max_length=500, verbose_name='摘要')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=15, verbose_name='申请金额')),
                ('payee', models.CharField(max_length=200, verbose_name='收款主体')),
                ('status', models.CharField(choices=[('pending', '待审批'), ('approved', '审批通过'), ('rejected', '已拒绝'), ('canceled', '已撤销')], db_index=True, default='pending', max_length=20, verbose_name='审批状态')),
                ('archived', models.BooleanField(db_index=True, default=False, verbose_name='是否归档')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approval_records', to='paikuan.paikuanuser')),
            ],
            options={'db_table': 'paikuan_approval_records', 'ordering': ['-created_at']},
        )
    ]
