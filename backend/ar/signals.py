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


@receiver([post_save, post_delete], sender='ar.AdvanceWriteoff')
def update_advance_on_writeoff_change(sender, instance, **kwargs):
    """核销变动 → 重算所属预收/预付的已核销与未核销余额。"""
    from django.core.exceptions import ValidationError
    try:
        record = instance.advance_record
        record.recompute_derived(save=True)
    except ValidationError:
        # Re-raise so callers inside transaction.atomic() get a rollback
        raise
    except Exception:
        pass


@receiver([post_save, post_delete], sender='ar.AdvanceWriteoff')
def update_payment_prepaid_offset(sender, instance, **kwargs):
    """预付核销变动时重算关联排款的预付冲抵金额，现金流视图从 paid 扣除，防双重计。"""
    from decimal import Decimal as _D
    from django.db.models import Sum as _Sum
    payment_id = instance.payment_id
    if not payment_id:
        return
    try:
        from ar.models import AdvanceWriteoff as _AW
        from paikuan.models import Payment as _Payment
        total = (_AW.objects.filter(payment_id=payment_id)
                 .aggregate(s=_Sum('amount'))['s'] or _D('0'))
        _Payment.objects.filter(pk=payment_id).update(prepaid_offset_amount=total)
    except Exception:
        pass


@receiver(post_delete, sender='ar.AdvanceWriteoff')
def delete_linked_offset_payment(sender, instance, **kwargs):
    """删除预收核销时，连带删除其生成的「预收抵扣」回款，恢复应收 outstanding。"""
    if not instance.ar_payment_id:
        return
    from ar.models import ARPayment
    try:
        ARPayment.objects.filter(pk=instance.ar_payment_id).delete()
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

    # 项目交付部门变更 → 同步其全部应收的反范式 delivery_dept（否则应收仍挂旧部门，
    # 影响部门筛选/权限/聚合）。仅更新不一致的行。
    try:
        ARRecord.objects.filter(project=instance).exclude(
            delivery_dept=instance.delivery_dept).update(delivery_dept=instance.delivery_dept)
    except Exception:
        pass

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


def _close_dunning_actions(record_id, reason, status='done'):
    """关闭与某条应收记录关联的未完成催款行动项（软关联 source_signal.ar_record_id）。"""
    from django.utils import timezone as _tz
    from ar.models import ActionItem
    try:
        qs = ActionItem.objects.filter(category='collection',
                                       status__in=['open', 'in_progress'])
        for item in qs.only('id', 'source_signal', 'description', 'status'):
            if (item.source_signal or {}).get('ar_record_id') != record_id:
                continue
            item.status = status
            item.resolved_at = _tz.now()
            item.description = ((item.description + '\n') if item.description else '') + reason
            item.save(update_fields=['status', 'resolved_at', 'description', 'updated_at'])
    except Exception:
        pass


@receiver([post_save, post_delete], sender='ar.ARPayment')
def auto_close_dunning_on_settle(sender, instance, **kwargs):
    """回款使应收结清 → 自动完成其催款任务（催款闭环收口）。
    在 update_ar_record_on_payment_change 重算之后触发（receiver 按注册顺序执行）。"""
    try:
        record = instance.ar_record
        if (record.outstanding_amount or 0) <= 0:
            _close_dunning_actions(record.id, '系统自动完成：该笔应收已结清')
    except Exception:
        pass


@receiver(post_delete, sender='ar.ARRecord')
def auto_dismiss_dunning_on_record_delete(sender, instance, **kwargs):
    """应收记录删除 → 其催款任务自动置为已忽略，避免残留死任务。"""
    _close_dunning_actions(instance.pk, '系统自动忽略：关联应收记录已删除', status='dismissed')


from django.db.models.signals import pre_delete  # noqa: E402


@receiver(pre_delete, sender='ar.ARPayment')
def delete_orphan_writeoff_on_offset_payment_delete(sender, instance, **kwargs):
    """「预收抵扣」回款被级联删除（删记录/删项目）时，反向删除其预收核销，
    恢复预收余额——否则核销悬空、预收余额永远少一块。
    正向删除（删核销→信号删回款）时核销已不存在，filter 落空天然防递归。"""
    if instance.source != '预收抵扣':
        return
    from ar.models import AdvanceWriteoff
    try:
        AdvanceWriteoff.objects.filter(ar_payment_id=instance.pk).delete()
    except Exception:
        pass
