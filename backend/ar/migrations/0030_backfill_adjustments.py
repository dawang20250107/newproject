# 历史差额回填：account_diff_adjustment ≠ 0 的存量记录各生成一条调整明细，
# 使「合计 = 明细之和」的派生不变量从迁移完成那一刻起成立。
from django.db import migrations


def backfill(apps, schema_editor):
    ARRecord = apps.get_model('ar', 'ARRecord')
    ARAdjustment = apps.get_model('ar', 'ARAdjustment')
    batch = []
    qs = (ARRecord.objects.exclude(account_diff_adjustment=0)
          .values_list('id', 'account_diff_adjustment'))
    for rid, amt in qs.iterator():
        batch.append(ARAdjustment(ar_record_id=rid, amount=amt,
                                  reason='历史差额（由单字段迁移生成）'))
        if len(batch) >= 500:
            ARAdjustment.objects.bulk_create(batch)
            batch = []
    if batch:
        ARAdjustment.objects.bulk_create(batch)


def reverse(apps, schema_editor):
    ARAdjustment = apps.get_model('ar', 'ARAdjustment')
    ARAdjustment.objects.filter(reason='历史差额（由单字段迁移生成）').delete()


class Migration(migrations.Migration):
    dependencies = [('ar', '0029_arproject_cycle_start_day_aradjustment')]
    operations = [migrations.RunPython(backfill, reverse)]
