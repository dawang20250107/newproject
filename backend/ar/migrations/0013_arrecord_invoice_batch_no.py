from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0012_remove_arproject_customer_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='arrecord',
            name='invoice_batch_no',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='合并开票批次号；相同批次号的记录将合并为一张发票',
                max_length=50,
                verbose_name='开票批次号',
            ),
        ),
    ]
