import calendar
import datetime

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


@receiver([post_save, post_delete], sender='ar.ARPayment')
def update_ar_record_on_payment_change(sender, instance, **kwargs):
    from django.core.exceptions import ValidationError
    try:
        record = instance.ar_record
        record.recompute_derived(save=True)
    except ValidationError:
        # Re-raise so callers inside transaction.atomic() get a rollback
        raise
    except Exception:
        pass


@receiver(post_save, sender='ar.ARProject')
def update_ar_record_due_dates_on_project_change(sender, instance, **kwargs):
    """When a project's total_days changes, recompute due_date for all linked ARRecords."""
    from ar.models import ARRecord
    total_days = instance.total_days
    updates = []
    for rec in instance.ar_records.only('id', 'operation_year', 'operation_month', 'due_date'):
        try:
            last_day = calendar.monthrange(rec.operation_year, rec.operation_month)[1]
            eom = datetime.date(rec.operation_year, rec.operation_month, last_day)
            new_due = eom + datetime.timedelta(days=total_days)
            if new_due != rec.due_date:
                updates.append((rec.pk, new_due))
        except Exception:
            pass
    for pk, due in updates:
        ARRecord.objects.filter(pk=pk).update(due_date=due)

    # Sync denormalised dept fields on budget records when project info changes.
    # Budget models link via project_no (a stable natural key), not FK.
    if not instance.project_no:
        return
    from ar.models import CollectionBudget, PaymentBudget
    dept_update = {
        'delivery_dept': instance.delivery_dept,
        'sub_dept': instance.sub_dept,
    }
    try:
        CollectionBudget.objects.filter(project_no=instance.project_no).update(**dept_update)
        PaymentBudget.objects.filter(project_no=instance.project_no).update(**dept_update)
    except Exception:
        pass
