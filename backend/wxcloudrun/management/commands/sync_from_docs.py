"""
Django management command: sync_from_docs
从腾讯文档同步所有数据到 MySQL
"""
import sys
from io import StringIO
from django.core.management.base import BaseCommand, CommandError
import sync_sheets


class Command(BaseCommand):
    help = '从腾讯文档同步所有业务数据到本地数据库'

    def handle(self, *args, **options):
        try:
            sync_sheets.main()
            self.stdout.write(self.style.SUCCESS('同步完成'))
        except Exception as e:
            raise CommandError(f'同步失败: {e}')
