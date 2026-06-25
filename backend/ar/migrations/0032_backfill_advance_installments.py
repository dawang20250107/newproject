# 历史预收/预付回填：每条记录生成一笔初始收付明细，使
# 「advance_amount = 明细之和」的派生不变量从迁移完成起成立。
from django.db import migrations


def backfill(apps, schema_editor):
    AdvanceRecord = apps.get_model('ar', 'AdvanceRecord')
    AdvanceInstallment = apps.get_model('ar', 'AdvanceInstallment')
    import datetime
    batch = []
    qs = AdvanceRecord.objects.exclude(advance_amount=0).values_list(
        'id', 'advance_amount', 'occur_date', 'occur_year', 'occur_month')
    for rid, amt, od, oy, om in qs.iterator():
        date = od or datetime.date(oy or 2000, om or 1, 1)
        batch.append(AdvanceInstallment(
            advance_record_id=rid, install_no=1, amount=amt, occur_date=date,
            notes='历史初始金额（由单字段迁移生成）'))
        if len(batch) >= 500:
            AdvanceInstallment.objects.bulk_create(batch)
            batch = []
    if batch:
        AdvanceInstallment.objects.bulk_create(batch)


def reverse(apps, schema_editor):
    AdvanceInstallment = apps.get_model('ar', 'AdvanceInstallment')
    AdvanceInstallment.objects.filter(notes='历史初始金额（由单字段迁移生成）').delete()


class Migration(migrations.Migration):
    dependencies = [('ar', '0031_advanceinstallment')]
    operations = [migrations.RunPython(backfill, reverse)]
