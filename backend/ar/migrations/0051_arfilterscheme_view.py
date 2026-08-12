# A3+B5: 筛选方案增加视图快照（列头筛选 colFilters + 列头排序 sort/order），
# 历史方案默认 '{}' → 套用时列头回到干净状态。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ar", "0050_alter_arrecord_options_alter_arrecord_managers_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="arfilterscheme",
            name="view",
            field=models.TextField(
                blank=True, default="{}", verbose_name="视图快照(JSON)"
            ),
        ),
    ]
