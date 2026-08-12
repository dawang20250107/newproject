#!/bin/bash
# SessionStart hook：云端容器（Claude Code on the web）开机自举。
# 容器回收后重建时自动恢复：Python 依赖、前端 node_modules、演示数据库。
# 幂等：重复运行安全；本地开发环境（非云端）直接跳过。
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# ── 后端依赖 ──────────────────────────────────────────────────────────────
# cffi：系统自带 cryptography 缺 _cffi_backend 会让 PyJWT 导入崩溃，显式补装
pip install -q -r backend/requirements.txt cffi

# ── 前端依赖 ──────────────────────────────────────────────────────────────
if [ ! -x frontend/node_modules/.bin/vite ]; then
  (cd frontend && npm install --no-audit --no-fund)
fi

# ── 演示数据库（仅首建；已存在则只补迁移）────────────────────────────────
if [ ! -f backend/db.sqlite3 ]; then
  (
    cd backend
    python manage.py migrate --no-input
    python manage.py seed_demo
    python manage.py shell -c "
from paikuan.models import PaikuanUser
u, created = PaikuanUser.objects.get_or_create(phone='13900000001', defaults=dict(
    name='演示超管', role='super_admin', job_title='finance_director',
    departments=['集团总部','劳务事业部','运输事业部','自营事业部','阔展事业部','多式联运事业部','供应链事业部'],
    is_active=True, is_approved=True))
if created:
    u.set_password('Demo123456'); u.save()
print('demo super_admin ready, created=', created)
"
  ) || echo "WARN: 演示库初始化失败（不阻塞会话，可手动 migrate+seed_demo）"
else
  (cd backend && python manage.py migrate --no-input) \
    || echo "WARN: 迁移失败（不阻塞会话）"
fi

echo "session-start bootstrap done"
