# Repoint ImportBatch.uploaded_by from the retired CaiwuUser to the unified
# platform account (PaikuanUser). See platform-integration Stage 2+3.
from django.db import migrations, models
import django.db.models.deletion


def clear_legacy_uploader(apps, schema_editor):
    """Null out existing uploaded_by_id values before the FK is repointed.

    They reference legacy CaiwuUser primary keys, which have no correspondence
    in the PaikuanUser table. Leaving them would display the wrong uploader and
    would fail FK validation on MySQL when the new constraint is added.
    Historical uploader attribution is dropped; new uploads record the correct
    PaikuanUser going forward.
    """
    ImportBatch = apps.get_model("caiwu", "ImportBatch")
    ImportBatch.objects.using(schema_editor.connection.alias).update(uploaded_by=None)


class Migration(migrations.Migration):

    dependencies = [
        ("paikuan", "0009_alter_payment_plan_adjustment"),
        ("caiwu", "0005_fix_l1_is_profit_driver"),
    ]

    operations = [
        migrations.RunPython(clear_legacy_uploader, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="importbatch",
            name="uploaded_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="caiwu_batches",
                to="paikuan.paikuanuser",
            ),
        ),
    ]
