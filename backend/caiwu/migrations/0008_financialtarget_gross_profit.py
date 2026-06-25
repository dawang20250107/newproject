from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('caiwu', '0007_financialtarget'),
    ]

    operations = [
        migrations.AddField(
            model_name='financialtarget',
            name='target_gross_profit',
            field=models.DecimalField(
                verbose_name='经营毛利目标',
                max_digits=15,
                decimal_places=2,
                default=0,
            ),
        ),
        migrations.AlterField(
            model_name='financialtarget',
            name='target_profit',
            field=models.DecimalField(
                verbose_name='经营净利目标',
                max_digits=15,
                decimal_places=2,
                default=0,
            ),
        ),
    ]
