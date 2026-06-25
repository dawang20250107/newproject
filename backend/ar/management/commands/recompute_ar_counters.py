"""对账 ARRecord.activity_count / attachment_count 计数器。

计数器用 F()+1/-1 增量维护，正常路径恒准；但数据迁移、批量脚本或任何绕过
视图层的写入都可能让它与真实 COUNT 漂移。本命令用一次聚合查询把两个计数器
重算到与 ARActivity / ARAttachment 真实行数一致，作为生产兜底。

    python manage.py recompute_ar_counters            # 修复并落库
    python manage.py recompute_ar_counters --dry-run  # 只报告漂移，不写库
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from ar.models import ARRecord, ARActivity, ARAttachment


class Command(BaseCommand):
    help = '重算并修复 ARRecord 的 activity_count / attachment_count 计数器'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='只报告漂移，不写库')

    def handle(self, *args, **opts):
        dry = opts['dry_run']

        act_counts = dict(
            ARActivity.objects.values('ar_record_id')
            .annotate(n=Count('id')).values_list('ar_record_id', 'n')
        )
        att_counts = dict(
            ARAttachment.objects.values('ar_record_id')
            .annotate(n=Count('id')).values_list('ar_record_id', 'n')
        )

        drifted = 0
        scanned = 0
        for rec in ARRecord.objects.only('id', 'activity_count', 'attachment_count').iterator():
            scanned += 1
            real_act = act_counts.get(rec.id, 0)
            real_att = att_counts.get(rec.id, 0)
            if rec.activity_count == real_act and rec.attachment_count == real_att:
                continue
            drifted += 1
            self.stdout.write(
                f'  记录 #{rec.id}: activity {rec.activity_count}->{real_act}, '
                f'attachment {rec.attachment_count}->{real_att}'
            )
            if not dry:
                ARRecord.objects.filter(pk=rec.id).update(
                    activity_count=real_act, attachment_count=real_att,
                )

        verb = '发现' if dry else '已修复'
        self.stdout.write(self.style.SUCCESS(
            f'扫描 {scanned} 条记录，{verb} {drifted} 条计数器漂移。'
        ))
