from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


def migrate_pay_slots_to_installments(apps, schema_editor):
    Payment = apps.get_model('paikuan', 'Payment')
    PaymentInstallment = apps.get_model('paikuan', 'PaymentInstallment')
    batch = []
    # Use raw SQL to avoid decimal-conversion issues with SQLite integer defaults
    cursor = schema_editor.connection.cursor()
    cursor.execute(
        'SELECT id, pay1_date, pay1_amount, pay2_date, pay2_amount, pay3_date, pay3_amount '
        'FROM paikuan_payments'
    )
    rows = cursor.fetchall()
    for (pid, d1, a1, d2, a2, d3, a3) in rows:
        seq = 1
        for pay_date, pay_amount_raw in ((d1, a1), (d2, a2), (d3, a3)):
            try:
                pay_amount = Decimal(str(pay_amount_raw or 0))
            except Exception:
                pay_amount = Decimal('0')
            if pay_date and pay_amount > Decimal('0'):
                batch.append(PaymentInstallment(
                    payment_id=pid,
                    seq=seq,
                    pay_date=pay_date,
                    pay_amount=pay_amount,
                    notes='',
                ))
                seq += 1
    PaymentInstallment.objects.bulk_create(batch)


def reverse_installments_to_pay_slots(apps, schema_editor):
    PaymentInstallment = apps.get_model('paikuan', 'PaymentInstallment')
    cursor = schema_editor.connection.cursor()
    cursor.execute('SELECT DISTINCT payment_id FROM paikuan_payment_installments')
    pids = [r[0] for r in cursor.fetchall()]
    ph = '%s' if schema_editor.connection.vendor != 'sqlite' else '?'
    for pid in pids:
        insts = list(PaymentInstallment.objects.filter(payment_id=pid).order_by('seq', 'pay_date')[:3])
        vals = {}
        for idx, slot in enumerate(('pay1', 'pay2', 'pay3')):
            if idx < len(insts):
                vals[f'{slot}_date'] = insts[idx].pay_date
                vals[f'{slot}_amount'] = insts[idx].pay_amount
            else:
                vals[f'{slot}_date'] = None
                vals[f'{slot}_amount'] = 0
        cursor.execute(
            f'UPDATE paikuan_payments SET pay1_date={ph}, pay1_amount={ph}, pay2_date={ph}, pay2_amount={ph}, '
            f'pay3_date={ph}, pay3_amount={ph} WHERE id={ph}',
            [vals['pay1_date'], float(vals['pay1_amount']),
             vals['pay2_date'], float(vals['pay2_amount']),
             vals['pay3_date'], float(vals['pay3_amount']), pid]
        )


class Migration(migrations.Migration):

    dependencies = [
        ('paikuan', '0012_payment_applicant'),
    ]

    operations = [
        # 1. Create the installments table
        migrations.CreateModel(
            name='PaymentInstallment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('payment', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='installments',
                    to='paikuan.payment',
                )),
                ('seq', models.PositiveSmallIntegerField(db_index=True, default=0, verbose_name='序号')),
                ('pay_date', models.DateField(db_index=True, verbose_name='付款日期')),
                ('pay_amount', models.DecimalField(decimal_places=2, max_digits=15, verbose_name='付款金额')),
                ('notes', models.CharField(blank=True, default='', max_length=200, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': '付款明细',
                'db_table': 'paikuan_payment_installments',
                'ordering': ['seq', 'pay_date'],
            },
        ),

        # 2. Migrate existing pay1/2/3 data into installments
        migrations.RunPython(
            migrate_pay_slots_to_installments,
            reverse_code=reverse_installments_to_pay_slots,
        ),

        # 3. Remove the old fixed-slot fields from Payment
        migrations.RemoveField(model_name='payment', name='pay1_date'),
        migrations.RemoveField(model_name='payment', name='pay1_amount'),
        migrations.RemoveField(model_name='payment', name='pay2_date'),
        migrations.RemoveField(model_name='payment', name='pay2_amount'),
        migrations.RemoveField(model_name='payment', name='pay3_date'),
        migrations.RemoveField(model_name='payment', name='pay3_amount'),
    ]
