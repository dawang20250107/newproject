#!/bin/bash
# 排款系统部署脚本
# 前提：服务器上已有日报系统（kxt.service 跑在 8080）；本脚本不修改日报系统任何文件。
set -e

DEPLOY_DIR=/opt/paikuan
BACKEND_DIR=$DEPLOY_DIR/backend
VENV_DIR=$DEPLOY_DIR/venv
FRONTEND_DIST=$DEPLOY_DIR/frontend_dist
LOG_DIR=/var/log/paikuan

echo "=== [1/6] 创建目录 ==="
mkdir -p $BACKEND_DIR $FRONTEND_DIST $LOG_DIR
chown ubuntu:ubuntu $LOG_DIR

echo "=== [2/6] 创建 MySQL 数据库（使用 root 执行一次即可）==="
# 如果 paikuan 库和用户已存在，跳过此步
mysql -u root -p <<'SQL'
CREATE DATABASE IF NOT EXISTS paikuan
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'paikuan'@'localhost'
    IDENTIFIED BY '替换为强密码';

GRANT ALL PRIVILEGES ON paikuan.* TO 'paikuan'@'localhost';
FLUSH PRIVILEGES;
SQL

echo "=== [3/6] 同步代码（假设已通过 git pull / scp 上传到 $BACKEND_DIR）==="
# 例：git clone / rsync / scp backend/ $BACKEND_DIR/

echo "=== [4/6] Python 虚拟环境 & 依赖 ==="
python3 -m venv $VENV_DIR
$VENV_DIR/bin/pip install --upgrade pip
$VENV_DIR/bin/pip install -r $BACKEND_DIR/requirements.txt PyMySQL==1.1.1

echo "=== [5/6] 环境变量 & 数据库迁移 ==="
# 复制 .env（首次需手动填写，参考 .env.example）
[ -f $BACKEND_DIR/.env ] || cp $BACKEND_DIR/.env.example $BACKEND_DIR/.env
echo "⚠️  请确认 $BACKEND_DIR/.env 中的密码和 Secret 已填写！"

cd $BACKEND_DIR
$VENV_DIR/bin/python manage.py migrate --noinput

echo "=== [6/6] 注册 systemd 服务 & 更新 nginx ==="
# systemd 服务
cp $BACKEND_DIR/deploy/paikuan.service /etc/systemd/system/paikuan.service
systemctl daemon-reload
systemctl enable paikuan
systemctl restart paikuan

# nginx — 将 deploy/nginx.conf 中的两条 location 手动插入到
# /etc/nginx/sites-available/kxtshare.cloud 的 443 server{} 里
# （或用 include 方式）：
NGINX_CONF=/etc/nginx/sites-available/kxtshare.cloud
SNIPPET=$BACKEND_DIR/deploy/nginx.conf
if grep -q "/api/pk/" $NGINX_CONF 2>/dev/null; then
    echo "nginx 片段已存在，跳过插入"
else
    echo "⚠️  请手动将 $SNIPPET 中的 location 块插入到 $NGINX_CONF 的 443 server{} 中"
    echo "    插入位置：location / 代理行之前"
fi

nginx -t && systemctl reload nginx

echo ""
echo "=== 部署完成 ==="
echo "  前端访问：https://kxtshare.cloud/paikuan/"
echo "  后端 API：https://kxtshare.cloud/api/pk/"
echo "  日报系统：https://kxtshare.cloud/（未受影响）"
echo "  gunicorn 端口：8081（日报系统占用 8080）"
echo "  MySQL 库：paikuan（日报系统用 kxt 库）"
