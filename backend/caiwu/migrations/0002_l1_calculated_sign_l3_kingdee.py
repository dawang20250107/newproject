from django.db import migrations, models


# KXT standard L1 categories seeded once on first migration.
# (name, sort_order, is_calculated, sign, is_profit_driver)
_L1_SEEDS = [
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


def seed_l1(apps, schema_editor):
    L1Category = apps.get_model('caiwu', 'L1Category')
    for name, sort_order, is_calculated, sign, is_profit_driver in _L1_SEEDS:
        obj, created = L1Category.objects.get_or_create(name=name)
        if created or obj.sort_order == 0:
            obj.sort_order = sort_order
            obj.is_calculated = is_calculated
            obj.sign = sign
            obj.is_profit_driver = is_profit_driver
            obj.save()


class Migration(migrations.Migration):

    dependencies = [
        ('caiwu', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='l1category',
            name='is_calculated',
            field=models.BooleanField(
                default=False,
                help_text='计算行不接受导入数据，由报表自动推算（如运营毛利、经营净利）',
                verbose_name='计算行',
            ),
        ),
        migrations.AddField(
            model_name='l1category',
            name='sign',
            field=models.IntegerField(
                default=1,
                help_text='收入类填 1，成本/费用类填 -1，用于瀑布图方向判断',
                verbose_name='利润方向',
            ),
        ),
        migrations.AddField(
            model_name='l3category',
            name='kingdee_code',
            field=models.CharField(
                blank=True,
                default='',
                help_text='如 6001.03.01，用于金蝶明细账直接导入时的科目匹配',
                max_length=50,
                verbose_name='金蝶科目编码',
            ),
        ),
        migrations.RunPython(seed_l1, migrations.RunPython.noop),
    ]
