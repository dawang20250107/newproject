from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('caiwu', '0003_job_permission'),
    ]

    operations = [
        migrations.AddField(
            model_name='importbatch',
            name='batch_type',
            field=models.CharField(
                default='department_detail',
                max_length=30,
                verbose_name='表类型',
            ),
        ),
    ]
