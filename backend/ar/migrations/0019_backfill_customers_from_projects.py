from django.db import migrations


def backfill_customers(apps, schema_editor):
    """把存量项目的「客户名称」回填为客户实体并挂接。

    历史项目（客户正名之前导入的）可能有 customer_name 但 customer 未挂接。
    按唯一客户名 get_or_create，一个客户挂多个项目；幂等、不动应收金额。
    """
    ARProject = apps.get_model('ar', 'ARProject')
    Customer = apps.get_model('ar', 'Customer')

    cache = {}
    qs = ARProject.objects.filter(customer__isnull=True).exclude(customer_name='')
    for p in qs.iterator():
        name = (p.customer_name or '').strip()
        if not name:
            continue
        cust = cache.get(name)
        if cust is None:
            cust, _ = Customer.objects.get_or_create(
                name=name, defaults={'level': p.customer_level or ''})
            cache[name] = cust
        ARProject.objects.filter(pk=p.pk).update(customer=cust)


def noop(apps, schema_editor):
    # 反向：不删客户（避免误伤手工新建的客户），仅留空
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0018_rename_contract_name_to_customer_name'),
    ]

    operations = [
        migrations.RunPython(backfill_customers, noop),
    ]
