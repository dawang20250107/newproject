# 历史排款挂链回填：静默ID（approval FK）上线前由审批生成的付款记录是
# 独立行、未挂链。按审批单号+收款方+部门唯一匹配时补挂，使旧审批也能
# 继续分批排款；占位审批号(全0)或多条匹配（旧模式分批）不猜、保持独立。
from django.db import migrations


def link(apps, schema_editor):
    Payment = apps.get_model('paikuan', 'Payment')
    ApprovalRecord = apps.get_model('paikuan', 'ApprovalRecord')
    for rec in ApprovalRecord.objects.exclude(approval_number='').iterator():
        no = rec.approval_number or ''
        if not no or set(no) == {'0'}:
            continue
        if Payment.objects.filter(approval=rec).exists():
            continue
        cand = Payment.objects.filter(approval__isnull=True, approval_number=no,
                                      payee=rec.payee, department=rec.department)
        if cand.count() == 1:
            cand.update(approval_id=rec.id)


class Migration(migrations.Migration):
    dependencies = [('paikuan', '0022_backfill_plan_items')]
    operations = [migrations.RunPython(link, migrations.RunPython.noop)]
