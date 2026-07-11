from django.db import migrations


def backfill_method(apps, schema_editor):
    """历史回款迁移：现有「现金回款」（source='回款'，此前无方式维度）统一置为
    「银行转账」（银行回款）。非回款来源（预收抵扣/内部往来）方式无意义，保持留空。"""
    ARPayment = apps.get_model('ar', 'ARPayment')
    ARPayment.objects.filter(source='回款', method='').update(method='银行转账')


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0044_arpayment_account_arpayment_method'),
    ]

    # 反向为 noop：'' → '银行转账' 的回填不可逆——上线后新回款默认就是「银行转账」，
    # 与回填行无法区分，若反向清空会误删用户/接口正当选择的「银行转账」。回滚仅需
    # 继续退到 0044（删列）即可，不应在此做有损的近似还原。
    operations = [
        migrations.RunPython(backfill_method, migrations.RunPython.noop),
    ]
