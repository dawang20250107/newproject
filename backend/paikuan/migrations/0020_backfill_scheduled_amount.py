# 历史归档审批 = 当年一次性排满：scheduled_amount 回填为申请金额，
# 使「已排款/剩余」口径对存量数据立即成立。
from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    ApprovalRecord = apps.get_model('paikuan', 'ApprovalRecord')
    ApprovalRecord.objects.filter(archived=True).update(scheduled_amount=F('amount'))


class Migration(migrations.Migration):
    dependencies = [('paikuan', '0019_approvalrecord_scheduled_amount')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
