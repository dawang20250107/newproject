from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


@receiver([post_save, post_delete], sender='ar.ARPayment')
def update_ar_record_on_payment_change(sender, instance, **kwargs):
    try:
        record = instance.ar_record
        record.recompute_derived(save=True)
    except Exception:
        pass
