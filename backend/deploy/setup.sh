#!/bin/bash
set -e

echo "=== 部署排款系统 ==="

# 1. 安装 Python 依赖
cd /opt/kxt/backend
pip3 install -r requirements.txt

# 2. 运行数据库迁移
python3 manage.py migrate --noinput

# 3. 构建前端（在开发机上执行 npm run build 后把 frontend_dist 上传）
# cd /opt/kxt/frontend && npm run build

# 4. 复制 nginx 配置
cp /opt/kxt/backend/deploy/nginx.conf /etc/nginx/sites-available/paikuan
ln -sf /etc/nginx/sites-available/paikuan /etc/nginx/sites-enabled/paikuan
nginx -t && systemctl reload nginx

# 5. 安装并启动 systemd 服务
cp /opt/kxt/backend/deploy/kxt.service /etc/systemd/system/kxt.service
systemctl daemon-reload
systemctl enable kxt
systemctl restart kxt

echo "=== 部署完成 ==="
