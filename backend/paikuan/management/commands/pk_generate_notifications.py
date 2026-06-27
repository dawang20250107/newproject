"""主动为全体活跃用户生成待办通知（供外部调度器调用，配合懒生成兜底）。

    # 每个工作日 08:00 主动推送待办通知
    0 8 * * 1-5 cd /app/backend && python manage.py pk_generate_notifications

懒生成（用户拉通知时）已能保证看到通知；本命令用于「用户未登录也提前备好」，
两者共用 _ensure_notifications，dedup_key 保证幂等、不会重复。
"""
from django.core.management.base import BaseCommand

from paikuan.models import PaikuanUser
from paikuan.views import _ensure_notifications


class Command(BaseCommand):
    help = '为全体活跃已审批用户预生成待办通知（幂等）'

    def handle(self, *args, **opts):
        users = PaikuanUser.objects.filter(is_active=True, is_approved=True)
        total_users = 0
        total_created = 0
        for u in users:
            try:
                created = _ensure_notifications(u)
            except Exception as e:
                self.stderr.write(f'用户 {u.id} 生成失败：{e}')
                continue
            if created:
                total_users += 1
                total_created += created
        self.stdout.write(self.style.SUCCESS(
            f'已为 {total_users} 名用户生成 {total_created} 条新通知'))
