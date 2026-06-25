from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0004_ar_record_outstanding_check_constraint'),
    ]

    operations = [
        migrations.RenameField(
            model_name='arproject',
            old_name='settlement_wait_days',
            new_name='post_invoice_days',
        ),
    ]
