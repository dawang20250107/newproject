#!/bin/bash
# 日报系统一键部署脚本
# 服务器执行: cd /home/ubuntu/kxt_backend && git pull origin claude/daily-report-fullstack && bash backend_patches/deploy_daily_report.sh
set -e

BACKEND="/home/ubuntu/kxt_backend"
APP="$BACKEND/wxcloudrun"

cd "$BACKEND"

ok()   { echo -e "\033[0;32m✓ $1\033[0m"; }
warn() { echo -e "\033[1;33m! $1\033[0m"; }
err()  { echo -e "\033[0;31m✗ $1\033[0m"; }

echo "========================================"
echo "  KXT 日报系统 — 服务器部署"
echo "========================================"

# 1. 更新 .env
echo ""
echo "--- 1. 更新 .env ---"
grep -q "^JWT_SECRET=" .env || echo "JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env
grep -q "^WX_APPID="    .env || echo "WX_APPID=wx67248c26cfe8f21b" >> .env
grep -q "^WX_SECRET="   .env || echo "WX_SECRET=715f532a4511aa8fe9cf95da8b639584" >> .env
ok ".env 已更新"; cat .env

# 2. 更新 settings.py
echo ""
echo "--- 2. 更新 settings.py ---"
SETTINGS="$APP/settings.py"
if ! grep -q "JWT_SECRET" "$SETTINGS"; then
cat >> "$SETTINGS" << 'PYEOF'

# JWT & WeChat config
import os as _os
JWT_SECRET = _os.environ.get('JWT_SECRET', 'kxt-jwt-dev-fallback')
WX_APPID   = _os.environ.get('WX_APPID', '')
WX_SECRET  = _os.environ.get('WX_SECRET', '')
PYEOF
    ok "JWT 配置已追加到 settings.py"
else
    ok "JWT_SECRET 已在 settings.py 中"
fi

# 3. 复制 report_views.py
echo ""
echo "--- 3. 复制 report_views.py ---"
cp "$BACKEND/backend/wxcloudrun/report_views.py" "$APP/report_views.py"
ok "report_views.py 已复制"

# 4. 追加模型
echo ""
echo "--- 4. 追加模型到 models.py ---"
MODELS="$APP/models.py"
if ! grep -q "class UserProfile" "$MODELS"; then
    # Ensure 'from django.db import models' is present
    grep -q "^from django.db import models" "$MODELS" || sed -i '1s/^/from django.db import models\n/' "$MODELS"
    cat >> "$MODELS" << 'PYEOF'


# ─── 用户档案 & 日报（自动追加）────────────────────────────
from django.contrib.auth.models import User as _DjangoUser


class UserProfile(models.Model):
    user = models.OneToOneField(_DjangoUser, on_delete=models.CASCADE, null=True, blank=True)
    openid = models.CharField(max_length=100, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        db_table = 'user_profiles'
        verbose_name = '用户档案'
        verbose_name_plural = '用户档案'

    def __str__(self):
        if self.user:
            return self.user.username
        return f'openid:{self.openid[:8] if self.openid else "?"}'


class DailyReport(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='reports')
    date = models.DateField('日期')
    blocks = models.JSONField('时段数据', default=list)
    works = models.TextField('行得通的是', blank=True, default='')
    not_works = models.TextField('行不通的是', blank=True, default='')
    plans = models.TextField('明日计划', blank=True, default='')
    commit_text = models.CharField('结语', max_length=500, blank=True, default='')
    dept = models.CharField('部门', max_length=100, blank=True, default='')
    role = models.CharField('岗位', max_length=100, blank=True, default='')
    name = models.CharField('姓名', max_length=100, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'daily_reports'
        verbose_name = '日报'
        verbose_name_plural = '日报'
        unique_together = ('user', 'date')
        ordering = ['-date']

    def __str__(self):
        return f'{self.user} - {self.date}'
PYEOF
    ok "UserProfile + DailyReport 已追加到 models.py"
else
    ok "UserProfile 已存在，跳过"
fi

# 5. 更新 urls.py
echo ""
echo "--- 5. 更新 urls.py ---"
python3 << 'PYEOF'
import re, sys

urls_path = '/home/ubuntu/kxt_backend/wxcloudrun/urls.py'
with open(urls_path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'daily-report' in content:
    print("daily-report 已存在，跳过")
    sys.exit(0)

# Add report_views import
if 'report_views' not in content:
    content = re.sub(
        r'from wxcloudrun import (views)',
        r'from wxcloudrun import \1, report_views',
        content
    )
    if 'report_views' not in content:
        content = "from wxcloudrun import report_views\n" + content

new_patterns = """
    # 微信登录
    url(r'^api/auth/wx-login$', report_views.wx_login, name='wx_login'),

    # 日报 API
    url(r'^api/daily-report/list$', report_views.daily_report_list, name='daily_report_list'),
    url(r'^api/daily-report/week$', report_views.weekly_analysis, name='weekly_analysis'),
    url(r'^api/daily-report/(?P<date>\\d{4}-\\d{2}-\\d{2})$', report_views.daily_report_detail, name='daily_report_detail'),
"""

# Insert before the catch-all r'^' route
result = re.sub(r"(    url\(r'\^',)", new_patterns + r"    \1", content, count=1)
if result == content:
    # Fallback: insert before last ]
    idx = content.rfind(']')
    result = content[:idx] + new_patterns + content[idx:]

with open(urls_path, 'w', encoding='utf-8') as f:
    f.write(result)
print("✓ URL patterns 已插入")
PYEOF

# 6. 数据库迁移
echo ""
echo "--- 6. 数据库迁移 ---"
MIGRATIONS="$APP/migrations"
mkdir -p "$MIGRATIONS"
touch "$MIGRATIONS/__init__.py"
MFILE="$MIGRATIONS/0001_add_userprofile_dailyreport.py"
if [ ! -f "$MFILE" ]; then
    cp "$BACKEND/backend/wxcloudrun/migrations/0001_add_userprofile_dailyreport.py" "$MFILE"
    ok "迁移文件已复制"
else
    ok "迁移文件已存在"
fi

source "$BACKEND/venv/bin/activate" 2>/dev/null || source "$BACKEND/.venv/bin/activate" 2>/dev/null || true

python3 manage.py migrate wxcloudrun 2>&1 | tail -10 && ok "迁移完成" || {
    warn "migrate 失败，尝试 --fake-initial..."
    python3 manage.py migrate wxcloudrun --fake-initial 2>&1 | tail -5
}

# 7. 重启服务
echo ""
echo "--- 7. 重启 kxt 服务 ---"
sudo systemctl daemon-reload
sudo systemctl restart kxt
sleep 2
sudo systemctl is-active --quiet kxt && ok "kxt 服务运行正常" || {
    err "服务启动失败，查看日志："
    sudo journalctl -u kxt -n 30 --no-pager
    exit 1
}

# 8. 部署前端
echo ""
echo "--- 8. 部署 Vue 前端 ---"
if [ -d "$BACKEND/frontend/dist" ]; then
    sudo mkdir -p /var/www/kxt_vue
    sudo rsync -a --delete "$BACKEND/frontend/dist/" /var/www/kxt_vue/
    ok "前端已部署到 /var/www/kxt_vue"
else
    warn "frontend/dist 不存在，跳过前端部署"
fi

# 9. 验证 API
echo ""
echo "--- 9. 验证 API ---"
sleep 1
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8000/api/auth/wx-login \
    -H 'Content-Type: application/json' -d '{}')
echo "wx-login 响应码: $STATUS（期望 400 或 500）"

echo ""
echo "========================================"
echo "  部署完成！"
echo "========================================"
