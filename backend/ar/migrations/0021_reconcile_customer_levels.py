from django.db import migrations
from collections import Counter


def reconcile_levels(apps, schema_editor):
    """以客户为准对齐「客户等级 ↔ 项目等级」。
    每个客户取规范等级 = 客户已有等级；为空则取其项目中出现最多的非空等级；
    再回写客户并镜像到该客户全部项目。一次性修复历史分叉数据。
    """
    ARProject = apps.get_model('ar', 'ARProject')
    Customer = apps.get_model('ar', 'Customer')

    for c in Customer.objects.iterator():
        proj_levels = [(pl or '').strip() for pl in
                       ARProject.objects.filter(customer_id=c.id).values_list('customer_level', flat=True)]
        canonical = (c.level or '').strip()
        if not canonical:
            nonempty = [pl for pl in proj_levels if pl]
            if nonempty:
                canonical = Counter(nonempty).most_common(1)[0][0]
        if not canonical:
            continue
        if (c.level or '').strip() != canonical:
            c.level = canonical
            c.save(update_fields=['level', 'updated_at'])
        ARProject.objects.filter(customer_id=c.id).exclude(
            customer_level=canonical).update(customer_level=canonical)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0020_customer_date'),
    ]

    operations = [
        migrations.RunPython(reconcile_levels, noop),
    ]
