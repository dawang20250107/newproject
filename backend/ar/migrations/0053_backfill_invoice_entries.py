"""历史开票回填：已开票且未挂批次的应收记录 → 生成首条开票明细。

此后开票三字段（实际开票额/税额/开票日期）以明细为正源；挂批次的记录由
批次开票事件管理，不建明细。回填值与主表现值一致，派生重算零漂移。"""
from django.db import migrations


def backfill(apps, schema_editor):
    ARRecord = apps.get_model('ar', 'ARRecord')
    ARInvoiceEntry = apps.get_model('ar', 'ARInvoiceEntry')
    qs = (ARRecord.objects
          .filter(actual_invoice_amount__isnull=False)
          .filter(invoice_batch_no='')
          .filter(invoice_entries__isnull=True))
    entries = [
        ARInvoiceEntry(ar_record_id=r.id, entry_no=1,
                       amount=r.actual_invoice_amount,
                       tax_amount=r.tax_amount,
                       invoice_date=r.invoice_date)
        for r in qs.only('id', 'actual_invoice_amount', 'tax_amount', 'invoice_date')
    ]
    ARInvoiceEntry.objects.bulk_create(entries, batch_size=500)


def unfill(apps, schema_editor):
    apps.get_model('ar', 'ARInvoiceEntry').objects.filter(entry_no=1).delete()


class Migration(migrations.Migration):
    dependencies = [('ar', '0052_arinvoiceentry')]
    operations = [migrations.RunPython(backfill, unfill)]
