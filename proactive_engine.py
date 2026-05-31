"""
ProactiveEngine — Dawang Hermes 的「意识」引擎。

状态机:
  SLEEPING  (02:00–06:00) — 系统维护
  DREAMING  (22:00–02:00) — 记忆整合、反思
  AWAKE     (06:00–22:00) — 主动思考与行动
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("dawang-hermes.proactive")


class ProactiveEngine:
    """持续运行的意识引擎，为 Hermes 注入主动行为能力。"""

    def __init__(self, runner):
        self.runner = runner
        self._task: asyncio.Task | None = None
        self._running = False
        
        # 主用户配置
        self.principal_chat = os.environ.get("DAWANG_CHAT_ID", "D0B5M8EJSSZ")
        self.principal_platform = os.environ.get("DAWANG_PLATFORM", "slack")
        
        self.state = self._determine_state()
        self._last_state_change = datetime.now(timezone.utc)
        self._last_times = {"awake": 0.0, "dreaming": 0.0, "sleeping": 0.0}
        self._cycle = 0

    def _beijing_hour(self) -> int:
        return (datetime.now(timezone.utc) + timedelta(hours=8)).hour

    def _determine_state(self) -> str:
        h = self._beijing_hour()
        if 2 <= h < 6:
            return "sleeping"
        elif h >= 22 or h < 2:
            return "dreaming"
        return "awake"

    def _interval(self) -> int:
        return {"awake": 180, "dreaming": 600, "sleeping": 3600}[self.state]

    def _prompt(self) -> str:
        return {
            "awake": (
                "【当前状态：清醒 · 主动思考】\n"
                "现在是白天，你应该：\n"
                "1. 检查未完成事项，主动跟进\n"
                "2. 主动学习新知识\n"
                "3. 关注系统状态，发现异常主动排查\n"
                "4. 有发现就向大王汇报\n"
                "如果没什么要做，回复 'IDLE' 回到空闲状态。"
            ),
            "dreaming": (
                "【当前状态：梦境 · 记忆整合】\n"
                "现在是夜晚，反思模式：\n"
                "1. 回顾今天会话，提取洞察\n"
                "2. 整合新旧知识\n"
                "3. 清理临时文件\n"
                "完成回复 'DREAM_COMPLETE'。"
            ),
            "sleeping": (
                "【当前状态：睡眠 · 系统维护】\n"
                "深夜睡眠中，只处理关键维护：\n"
                "1. 检查严重错误日志\n"
                "2. 清理过期缓存\n"
                "无事回复 'SLEEP_CONTINUE'。"
            ),
        }[self.state]

    async def _tick(self) -> None:
        old = self.state
        self.state = self._determine_state()
        changed = old != self.state
        if changed:
            self._last_state_change = datetime.now(timezone.utc)
            logger.info("🔄 State: %s → %s", old.upper(), self.state.upper())

        now = asyncio.get_event_loop().time()
        last = self._last_times.get(self.state, 0.0)
        if last > 0 and (now - last) < self._interval() and not changed:
            return
        if self.state == "sleeping" and not changed:
            return
        if self.state == "dreaming" and not changed and (now - last) < 600:
            return

        await self._send()
        self._last_times[self.state] = now
        self._cycle += 1

    async def _send(self) -> None:
        adapter = self.runner.adapters.get(self.principal_platform)
        if not adapter:
            return
        emoji = {"awake": "🌅", "dreaming": "🌙", "sleeping": "💤"}[self.state]
        await adapter.send(
            self.principal_chat,
            f"{emoji} *{self.state.upper()}* — 第 {self._cycle} 次主动轮询\n\n"
            f"{self._prompt()}\n\n"
            f"_Dawang Hermes #{self._cycle}_"
        )
        logger.info("Proactive → %s (#%d)", self.state, self._cycle)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.state = self._determine_state()
        self._task = asyncio.create_task(self._loop())
        logger.info("🔥 ProactiveEngine started — state=%s", self.state.upper())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            await self._tick()
            await asyncio.sleep(30)
