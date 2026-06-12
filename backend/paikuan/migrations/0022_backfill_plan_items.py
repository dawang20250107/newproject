# 存量付款各生成一条计划明细（=原 计划日期+计划金额），
# 使「汇总=明细之和」的派生不变量对历史数据立即成立。
from django.db import migrations


def backfill(apps, schema_editor):
    Payment = apps.get_model('paikuan', 'Payment')
    PaymentPlanItem = apps.get_model('paikuan', 'PaymentPlanItem')
    batch = []
    for pid, pdate, amt in Payment.objects.values_list(
            'id', 'planned_date', 'total_amount').iterator():
        if not pdate:
            continue
        batch.append(PaymentPlanItem(payment_id=pid, seq=1, planned_date=pdate,
                                     amount=amt or 0, notes='历史计划（迁移生成）'))
        if len(batch) >= 500:
            PaymentPlanItem.objects.bulk_create(batch)
            batch = []
    if batch:
        PaymentPlanItem.objects.bulk_create(batch)


def reverse(apps, schema_editor):
    PaymentPlanItem = apps.get_model('paikuan', 'PaymentPlanItem')
    PaymentPlanItem.objects.filter(notes='历史计划（迁移生成）').delete()


class Migration(migrations.Migration):
    dependencies = [('paikuan', '0021_payment_approval_paymentplanitem')]
    operations = [migrations.RunPython(backfill, reverse)]
