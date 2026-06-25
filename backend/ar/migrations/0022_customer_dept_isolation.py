from django.db import migrations, models


def split_customers_by_dept(apps, schema_editor):
    """把全局唯一的客户按事业部拆分（同名客户在不同部门变成独立客户）。

    对每个客户：取其名下项目的所有交付部门。
    - 第一个部门留给原客户（设其 delivery_dept）；
    - 其余每个部门新建一个同名客户，并把该部门的项目改挂过去。
    无项目的客户（孤儿）保持 delivery_dept=''。
    """
    Customer = apps.get_model('ar', 'Customer')
    ARProject = apps.get_model('ar', 'ARProject')

    for cust in Customer.objects.all():
        projs = list(ARProject.objects.filter(customer_id=cust.id))
        depts = sorted({(p.delivery_dept or '') for p in projs if (p.delivery_dept or '')})
        if not depts:
            continue
        cust.delivery_dept = depts[0]
        cust.save(update_fields=['delivery_dept'])
        for d in depts[1:]:
            new_cust = Customer.objects.create(
                name=cust.name, delivery_dept=d, level=cust.level,
                contact=cust.contact, notes=cust.notes, customer_date=cust.customer_date)
            ARProject.objects.filter(customer_id=cust.id, delivery_dept=d).update(customer_id=new_cust.id)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0021_reconcile_customer_levels'),
    ]

    operations = [
        # 1) 加交付部门字段
        migrations.AddField(
            model_name='customer',
            name='delivery_dept',
            field=models.CharField('交付部门', max_length=50, blank=True, default='', db_index=True),
        ),
        # 2) 去掉 name 的全局唯一（拆分会产生同名客户）
        migrations.AlterField(
            model_name='customer',
            name='name',
            field=models.CharField('客户名称', max_length=200, db_index=True),
        ),
        # 3) 按部门拆分存量客户
        migrations.RunPython(split_customers_by_dept, noop),
        # 4) 改为 (客户名, 交付部门) 联合唯一
        migrations.AlterUniqueTogether(
            name='customer',
            unique_together={('name', 'delivery_dept')},
        ),
    ]
