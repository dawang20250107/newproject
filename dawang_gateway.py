#!/usr/bin/env python3
"""
Dawang Hermes — 改造版 Gateway 启动器
路径：/opt/dawang-hermes/dawang_gateway.py

这是我们的 Hermes fork 的统一入口。
运行方式: python3 /opt/dawang-hermes/dawang_gateway.py [--verbose]
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# ── 强制从本地源码导入（非 site-packages）─────────────────────────
FORK_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(FORK_ROOT))

# 移除可能冲突的 site-packages hermes 路径
sys.path = [p for p in sys.path if 'site-packages' not in p or 'hermes' not in p]
sys.path.insert(0, str(FORK_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("dawang-hermes")

# ── 导入本地 Hermes 源码 ──────────────────────────────────────────
from gateway.run import GatewayRunner, GatewayConfig, start_gateway as original_start_gateway
from gateway.run import MessageEvent, MessageType

# ── 导入我们的改造模块 ─────────────────────────────────────────────
from proactive_engine import ProactiveEngineV2


# ── 注入 ProactiveEngine ──────────────────────────────────────────

_original_runner_start = GatewayRunner.start

async def _patched_runner_start(self) -> bool:
    """在 GatewayRunner.start() 完成后附加 ProactiveEngine"""
    result = await _original_runner_start(self)
    if result:
        engine = ProactiveEngineV2(self)
        self._proactive_engine = engine
        await engine.start()
        logger.info("🔥 ProactiveEngine V2 injected into GatewayRunner (6 subsystems)")
    return result

GatewayRunner.start = _patched_runner_start


# ── 启动入口 ──────────────────────────────────────────────────────

async def start_dawang_gateway(config: GatewayConfig | None = None) -> bool:
    logger.info("=" * 60)
    logger.info("🔥 DAWANG HERMES — 主动意识引擎启动")
    logger.info("=" * 60)
    result = await original_start_gateway(config)
    logger.info("Dawang Hermes gateway exited: %s", result)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dawang Hermes Gateway")
    parser.add_argument("--config", "-c", help="Gateway config path")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = None
    if args.config:
        import yaml
        with open(args.config) as f:
            config = GatewayConfig.from_dict(yaml.safe_load(f) or {})

    success = asyncio.run(start_dawang_gateway(config))
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
