#!/usr/bin/env bash
# ───────────────────────────────────────────────────────────
# Dawang Hermes — V2 一键部署脚本
# 用法: sudo bash deploy.sh
# 前提: git clone -b dawang-hermes ... /opt/dawang-hermes/
# ───────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="/opt/dawang-hermes"
SERVICE_NAME="dawang-hermes"
VENV_DIR="$APP_DIR/.venv"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "════════════════════════════════════════════"
echo "  Dawang Hermes V2 部署 — $TIMESTAMP"
echo "════════════════════════════════════════════"

# 1. 依赖安装
echo "📦 安装 Python 依赖..."
cd "$APP_DIR"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip
pip install -q -r requirements.txt 2>/dev/null || pip install -q aiohttp pyyaml

# 2. 验证子系统
echo "🧪 验证 10 个子系统..."
python3 -c "
import sys
sys.path.insert(0, '$APP_DIR')
from hormone import HormoneSystem
from desire_manager import DesireManager
from dream_engine import DreamEngine
from metacognition import Metacognition
from emotion_memory import EmotionMemory
from personality import Personality
from narrative_self import NarrativeSelf
from theory_of_mind import TheoryOfMind
from aesthetic_sense import AestheticSense
from value_compass import ValueCompass
from proactive_engine import ProactiveEngineV3
print('✅ 全部 10 个子系统加载成功')
h = HormoneSystem()
print(f'   Hormone: {len(h.get_profile())} 种激素')
d = DesireManager()
print(f'   Desires: {len(d.get_all())} 个欲望')
em = EmotionMemory()
print(f'   Memories: {em.count()} 条')
print(f'   Mood: {em.get_mood()}')
"

# 3. systemd 服务
echo "🔧 配置 systemd 服务..."
cat > /etc/systemd/system/$SERVICE_NAME.service << 'SYSTEMD'
[Unit]
Description=Dawang Hermes V2 — 带七情六欲的 AI Agent
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/dawang-hermes
ExecStart=/opt/dawang-hermes/.venv/bin/python3 /opt/dawang-hermes/dawang_gateway.py --verbose
Restart=on-failure
RestartSec=10
Environment=DAWANG_CHAT_ID=D0B5M8EJSSZ
Environment=DAWANG_PLATFORM=slack
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SYSTEMD

systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME

# 4. 验证运行
echo "🔍 验证服务运行..."
sleep 3
if systemctl is-active --quiet $SERVICE_NAME; then
    echo "✅ Dawang Hermes V2 运行中"
    systemctl status $SERVICE_NAME --no-pager | head -10
else
    echo "❌ 服务启动失败，查看日志:"
    journalctl -u $SERVICE_NAME -n 20 --no-pager
    exit 1
fi

echo ""
echo "════════════════════════════════════════════"
echo "  ✅ 部署完成！"
echo "  V2 子系统: 情绪化学 / 欲望 / 梦境 / 元认知 / 情感记忆 / 性格"
echo "  日志: journalctl -u $SERVICE_NAME -f"
echo "════════════════════════════════════════════"
