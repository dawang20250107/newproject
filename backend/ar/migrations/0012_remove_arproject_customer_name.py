from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0011_arrecord_ar_records_operati_6fdc4c_idx_and_more'),
    ]

    operations = [
        # 客户名称与合同名称在业务上始终一致，移除冗余字段，统一以 contract_name 为准。
        migrations.RemoveField(
            model_name='arproject',
            name='customer_name',
        ),
    ]
