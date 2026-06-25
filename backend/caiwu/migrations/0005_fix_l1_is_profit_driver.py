from django.db import migrations

# Unconditionally patch all seeded L1 categories.
# Migration 0002's seed_l1 only updated records when created or sort_order==0,
# so manually-created L1 categories kept is_profit_driver=False (default).
_SEEDS = [
    ('主营业务收入', 10,  False,  1, True),
    ('主营业务成本', 20,  False, -1, True),
    ('税金成本',     30,  False, -1, False),
    ('运营毛利',     40,  True,   1, False),
    ('销售费用',     50,  False, -1, True),
    ('管理费用',     60,  False, -1, True),
    ('财务费用',     70,  False, -1, False),
    ('营业外收入',   80,  False,  1, False),
    ('营业外支出',   90,  False, -1, False),
    ('经营毛利',     100, True,   1, False),
    ('集团管理费用', 110, False, -1, True),
    ('经营净利',     120, True,   1, False),
]


def fix_l1_seeds(apps, schema_editor):
    L1Category = apps.get_model('caiwu', 'L1Category')
    for name, sort_order, is_calculated, sign, is_profit_driver in _SEEDS:
        obj, created = L1Category.objects.get_or_create(
            name=name,
            defaults=dict(
                sort_order=sort_order,
                is_calculated=is_calculated,
                sign=sign,
                is_profit_driver=is_profit_driver,
            ),
        )
        if not created:
            obj.sort_order = sort_order
            obj.is_calculated = is_calculated
            obj.sign = sign
            obj.is_profit_driver = is_profit_driver
            obj.save()


class Migration(migrations.Migration):

    dependencies = [
        ('caiwu', '0004_importbatch_type'),
    ]

    operations = [
        migrations.RunPython(fix_l1_seeds, migrations.RunPython.noop),
    ]
