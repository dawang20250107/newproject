# 差额调整「合计↔明细」对账回填。
#
# 不变量：ARRecord.account_diff_adjustment 应恒等于其 ARAdjustment 明细之和
# （signals.update_ar_record_on_adjustment_change 维护）。但存量数据里，凡是
# 经 seed/loaddata 或早期单字段写入而绕过明细链路的记录，会出现「合计有值、
# 明细为空」的漂移——时段合计按 adjust_date 归集明细，于是「调整额」显示为 0。
#
# 本迁移把漂移的记录补一条明细（差额 = 合计 − 现有明细之和），并以 operation_date
# 作为 adjust_date，使时段合计/周月归集恢复正确口径，且不动既有正确数据。
from django.db import migrations
from decimal import Decimal


def reconcile(apps, schema_editor):
    ARRecord = apps.get_model('ar', 'ARRecord')
    ARAdjustment = apps.get_model('ar', 'ARAdjustment')
    from django.db.models import Sum

    # 现有明细按记录汇总，便于求差额（避免 N 次子查询）
    ledger = {row['ar_record_id']: (row['s'] or Decimal('0'))
              for row in ARAdjustment.objects.values('ar_record_id').annotate(s=Sum('amount'))}

    batch = []
    qs = (ARRecord.objects.exclude(account_diff_adjustment=0)
          .values_list('id', 'account_diff_adjustment', 'operation_date', 'due_date'))
    for rid, total, op_date, due_date in qs.iterator():
        total = total or Decimal('0')
        gap = total - ledger.get(rid, Decimal('0'))
        if gap == 0:
            continue
        batch.append(ARAdjustment(
            ar_record_id=rid, amount=gap,
            reason='历史差额（合计↔明细对账回填）',
            adjust_date=op_date or due_date))
        if len(batch) >= 500:
            ARAdjustment.objects.bulk_create(batch)
            batch = []
    if batch:
        ARAdjustment.objects.bulk_create(batch)


def reverse(apps, schema_editor):
    ARAdjustment = apps.get_model('ar', 'ARAdjustment')
    ARAdjustment.objects.filter(reason='历史差额（合计↔明细对账回填）').delete()


class Migration(migrations.Migration):
    dependencies = [('ar', '0035_backfill_adjust_date')]
    operations = [migrations.RunPython(reconcile, reverse)]
