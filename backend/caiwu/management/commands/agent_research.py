"""同行/行业自动调研（定时任务）：搜索→读源→AI 提炼→查重→沉淀知识库。

用法（建议每周跑一次，接入 CloudRun 定时触发器 / crontab）：
    python manage.py agent_research                 # 默认主题组（覆盖各业务条线）
    python manage.py agent_research --topics "网络货运 监管新政,柴油价格走势"

无需搜索 Key（内置必应中国抓取）；需 DEEPSEEK_API_KEY 做情报提炼。
"""
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = '同行/行业自动调研并沉淀知识库（内置搜索，无需 Key；建议每周定时执行）'

    def add_arguments(self, parser):
        parser.add_argument('--topics', type=str, default='',
                            help='逗号分隔的调研主题；缺省用内置主题组')

    def handle(self, *args, **opts):
        if not getattr(settings, 'ENABLE_PEER_RESEARCH', False):
            self.stderr.write('同行"一键调研"未开启（ENABLE_PEER_RESEARCH 未启用）；'
                              '如需自动调研沉淀知识库，请设 ENABLE_PEER_RESEARCH=1')
            raise SystemExit(4)
        if not settings.DEEPSEEK_API_KEY:
            self.stderr.write('未配置 DEEPSEEK_API_KEY，无法提炼情报')
            raise SystemExit(2)
        from caiwu.views import _ai_budget_denied
        if _ai_budget_denied() is not None:
            self.stderr.write('今日 AI 额度已用完，调研中止（明日恢复或调高 AI_DAILY_TOKEN_BUDGET）')
            raise SystemExit(3)
        from caiwu.agent_research import run_research
        topics = [t.strip() for t in (opts['topics'] or '').split(',') if t.strip()] or None
        total_saved = 0
        for r in run_research(topics):
            total_saved += len(r['saved'])
            self.stdout.write(f"[{r['topic'][:36]}] 入库 {len(r['saved'])} 条，"
                              f"查重跳过 {r['skipped_dup']} 条"
                              + (f'，{r["note"]}' if r['note'] else ''))
            for k in r['saved']:
                self.stdout.write(f"   · {k['title']}")
        self.stdout.write(f'\n本轮共沉淀 {total_saved} 条行业情报')
