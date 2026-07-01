"""排款系统定时维护任务（供外部调度器 system cron / k8s CronJob 调用）。

无 Celery/Redis 依赖：所有定时任务收敛为幂等的管理命令，由部署侧的 cron 触发。
建议每日凌晨各调用一次，例如 crontab：

    # 每日 03:00 回收站/导出任务清理
    0 3 * * * cd /app/backend && python manage.py pk_housekeeping

涵盖：
  1. 回收站自动清理：软删（deleted_at 非空）超过保留天数的审批/付款记录彻底删除
  2. 导出任务清理：ExportJob 超过保留天数的记录连同文件字节一并删除（释放 DB 体积）
  3. 审计日志清理（可选，默认关闭，避免与既有 audit_logs_prune 重复）

所有动作幂等，可安全重复执行；--dry-run 只报告不写库。
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from paikuan.models import ApprovalRecord, Payment, ExportJob


class Command(BaseCommand):
    help = '排款系统定时维护：回收站自动清理 + 导出任务清理'

    def add_arguments(self, parser):
        parser.add_argument('--trash-days', type=int, default=30,
                            help='回收站记录保留天数，超过即彻底删除（默认 30）')
        parser.add_argument('--export-days', type=int, default=7,
                            help='导出任务保留天数，超过即删除（默认 7）')
        parser.add_argument('--dry-run', action='store_true',
                            help='只报告将清理的数量，不写库')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        now = timezone.now()
        trash_cutoff = now - timedelta(days=opts['trash_days'])
        export_cutoff = now - timedelta(days=opts['export_days'])

        # 1. 回收站：软删超过保留期的审批 / 付款记录彻底删除
        #    付款须先解绑来源审批的对账（_reconcile）——但这些记录已软删、不计入
        #    scheduled_amount，硬删不再改变对账口径，直接删除即可。
        appr_qs = ApprovalRecord.objects.filter(
            deleted_at__isnull=False, deleted_at__lt=trash_cutoff)
        pay_qs = Payment.objects.filter(
            deleted_at__isnull=False, deleted_at__lt=trash_cutoff)
        appr_n = appr_qs.count()
        pay_n = pay_qs.count()

        # 2. 导出任务：超过保留期的连同字节一并删除
        exp_qs = ExportJob.objects.filter(created_at__lt=export_cutoff)
        exp_n = exp_qs.count()

        if dry:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] 将清理：回收站审批 {appr_n} 条、回收站付款 {pay_n} 条、'
                f'导出任务 {exp_n} 条'))
            return

        appr_deleted = appr_qs.delete()[0] if appr_n else 0
        pay_deleted = pay_qs.delete()[0] if pay_n else 0
        exp_deleted = exp_qs.delete()[0] if exp_n else 0

        self.stdout.write(self.style.SUCCESS(
            f'清理完成：回收站审批 {appr_deleted} 行、回收站付款 {pay_deleted} 行、'
            f'导出任务 {exp_deleted} 行（含级联）'))
