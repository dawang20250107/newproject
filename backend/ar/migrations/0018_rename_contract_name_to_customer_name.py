from django.db import migrations, models


class Migration(migrations.Migration):
    """把 ARProject.contract_name 改名为 customer_name。

    「合同名称」字段实际存的就是客户公司名（与 customer FK 自动挂接同源），
    本次随产品口径将其正名为「客户名称」。RenameField 仅改列名、保留全部数据。
    """

    dependencies = [
        ('ar', '0017_action_item_model'),
    ]

    operations = [
        migrations.RenameField(
            model_name='arproject',
            old_name='contract_name',
            new_name='customer_name',
        ),
        migrations.AlterField(
            model_name='arproject',
            name='customer_name',
            field=models.CharField('客户名称', max_length=200),
        ),
    ]
