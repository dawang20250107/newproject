#!/bin/bash
set -e

REPO="https://github.com/dawang20250107/newproject.git"
BRANCH="claude/daily-report-fullstack"
APP_DIR="/opt/kxt"

echo "=== 1. 安装系统依赖 ==="
apt update && apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git mysql-client

echo "=== 2. 拉取代码 ==="
mkdir -p $APP_DIR
git clone -b $BRANCH $REPO $APP_DIR || (cd $APP_DIR && git pull origin $BRANCH)

echo "=== 3. 创建虚拟环境并安装依赖 ==="
python3 -m venv $APP_DIR/venv
$APP_DIR/venv/bin/pip install --upgrade pip
$APP_DIR/venv/bin/pip install -r $APP_DIR/backend/requirements.txt

echo "=== 4. 配置 .env ==="
if [ ! -f $APP_DIR/backend/.env ]; then
    cp $APP_DIR/backend/.env.example $APP_DIR/backend/.env
    echo "⚠️  请编辑 $APP_DIR/backend/.env 填入真实配置，然后重新运行此脚本"
    exit 1
fi

echo "=== 5. 数据库迁移 ==="
cd $APP_DIR/backend
$APP_DIR/venv/bin/python manage.py migrate --noinput

echo "=== 6. 配置日志目录 ==="
mkdir -p /var/log/kxt
chown ubuntu:ubuntu /var/log/kxt

echo "=== 7. 配置 systemd 服务 ==="
cp $APP_DIR/backend/deploy/kxt.service /etc/systemd/system/kxt.service
systemctl daemon-reload
systemctl enable kxt
systemctl restart kxt

echo "=== 8. 配置 nginx ==="
cp $APP_DIR/backend/deploy/nginx.conf /etc/nginx/sites-available/kxt
ln -sf /etc/nginx/sites-available/kxt /etc/nginx/sites-enabled/kxt
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "=== 9. 申请 SSL 证书 ==="
certbot --nginx -d kxtshare.cloud --non-interactive --agree-tos -m 你的邮箱@example.com

echo ""
echo "✅ 部署完成！访问 https://kxtshare.cloud 验证"
