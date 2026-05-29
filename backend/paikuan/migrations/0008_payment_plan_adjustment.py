from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('paikuan', '0007_add_payment_business_key_uniqueness'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='plan_adjustment',
            field=models.TextField('计划调整', blank=True, default=''),
        ),
    ]
