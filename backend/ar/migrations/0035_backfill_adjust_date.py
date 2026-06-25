# 差额调整回填日期：历史 adjust_date 为空的明细，按关联应收记录的运作日期回填
# （历史差额归入业务发生月，使时段合计可按调整日期分桶）；运作日期缺失时退化为
# created_at 当天。0030 迁移生成的「历史差额」明细均无日期，此处一并补齐。
from django.db import migrations


def backfill(apps, schema_editor):
    ARAdjustment = apps.get_model('ar', 'ARAdjustment')
    qs = (ARAdjustment.objects.filter(adjust_date__isnull=True)
          .select_related('ar_record'))
    batch = []
    for adj in qs.iterator():
        d = adj.ar_record.operation_date if adj.ar_record_id else None
        if d is None and adj.created_at:
            d = adj.created_at.date()
        if d is None:
            continue
        adj.adjust_date = d
        batch.append(adj)
        if len(batch) >= 500:
            ARAdjustment.objects.bulk_update(batch, ['adjust_date'])
            batch = []
    if batch:
        ARAdjustment.objects.bulk_update(batch, ['adjust_date'])


def reverse(apps, schema_editor):
    # 不可逆：无法区分回填值与原始值，保留数据不动。
    pass


class Migration(migrations.Migration):
    dependencies = [('ar', '0034_arpayment_counterparty_dept_alter_arpayment_source')]
    operations = [migrations.RunPython(backfill, reverse)]
