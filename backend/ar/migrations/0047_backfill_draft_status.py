from django.db import migrations


def backfill_draft_status(apps, schema_editor):
    """存量承兑汇票回款默认置为「未承兑」（持票未兑付），使承兑状态显式、口径明确；
    兑付后由用户改为「已承兑」进资金池。其它方式无承兑状态，保持留空。"""
    ARPayment = apps.get_model('ar', 'ARPayment')
    ARPayment.objects.filter(method='承兑汇票', draft_status='').update(draft_status='未承兑')


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0046_arpayment_draft_status'),
    ]

    # 反向 noop：'' → '未承兑' 的回填不可逆——上线后新承兑默认即「未承兑」，
    # 与回填行无法区分，回滚仅需继续退到 0046（删列）。
    operations = [
        migrations.RunPython(backfill_draft_status, migrations.RunPython.noop),
    ]
