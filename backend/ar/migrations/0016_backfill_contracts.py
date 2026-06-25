from django.db import migrations


def backfill_contracts(apps, schema_editor):
    """从现有 ARProject.contract_name 文本回填合同实体（增量、幂等、不改旧字段）。

    去重口径：(合同名 trim, 交付部门)。同名同部门的多个项目归并到同一合同，
    天然支持「1合同多项目」；跨部门同名视为不同合同（保守，避免误并）。
    若项目已有 customer 外键，则在合同上登记为主客户(ContractParty)。
    """
    ARProject = apps.get_model('ar', 'ARProject')
    Contract = apps.get_model('ar', 'Contract')
    ContractProject = apps.get_model('ar', 'ContractProject')
    ContractParty = apps.get_model('ar', 'ContractParty')

    cache = {}  # (name, dept) -> Contract
    for proj in ARProject.objects.all().iterator():
        name = (proj.contract_name or '').strip()
        if not name:
            continue
        dept = proj.delivery_dept or ''
        key = (name, dept)
        contract = cache.get(key)
        if contract is None:
            contract, _ = Contract.objects.get_or_create(
                name=name, delivery_dept=dept,
                defaults={'sign_date': proj.contract_date},
            )
            cache[key] = contract

        ContractProject.objects.get_or_create(
            contract=contract, project=proj,
            defaults={'is_primary': True},
        )
        if proj.customer_id:
            ContractParty.objects.get_or_create(
                contract=contract, customer_id=proj.customer_id,
                defaults={'role': 'main'},
            )


def unbackfill(apps, schema_editor):
    """回滚：清空回填生成的关联与合同（仅本迁移产生的数据全清）。"""
    apps.get_model('ar', 'ContractParty').objects.all().delete()
    apps.get_model('ar', 'ContractProject').objects.all().delete()
    apps.get_model('ar', 'Contract').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ar', '0015_contract_contractproject_contractparty_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_contracts, unbackfill),
    ]
