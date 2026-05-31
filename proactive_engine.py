"""
ProactiveEngine V2 — Dawang Hermes 的「意识」引擎。
══════════════════════════════════════════════════════════
状态机:
  SLEEPING  (02:00–06:00) — 系统维护，深度清理
  DREAMING  (22:00–02:00) — 创造性梦境，记忆整合
  AWAKE     (06:00–22:00) — 主动思考与行动，情绪流动

V2 新增子系统:
  hormone.py         — 五激素化学系统（多巴胺/血清素/皮质醇/催产素/无聊）
  desire_manager.py  — 欲望持久化 + 优先级仲裁
  dream_engine.py    — 创造性关联跳跃 + 直觉生成
  metacognition.py   — 自我状态感知（元认知）
  emotion_memory.py  — 情感记忆加权存储
  personality.py     — 性格演化（偏好/习惯/偏见）
══════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timezone, timedelta

from hormone import HormoneSystem
from desire_manager import DesireManager
from dream_engine import DreamEngine
from metacognition import Metacognition
from emotion_memory import EmotionMemory
from personality import Personality

logger = logging.getLogger("dawang-hermes.proactive_v2")


class ProactiveEngineV2:
    """持续运行的意识引擎 V2 — 让 Hermes 拥有七情六欲和梦想。"""

    # ── 状态机配置 ─────────────────────────────────────────────
    STATE_DURATIONS = {
        "awake":   180,    # 3 分钟 tick
        "dreaming": 600,   # 10 分钟 tick
        "sleeping": 3600,  # 1 小时 tick
    }
    DREAM_CYCLE_INTERVAL = 1800  # 梦境每 30 分钟运行一次完整循环

    def __init__(self, runner):
        self.runner = runner
        self._task: asyncio.Task | None = None
        self._running = False
        self._start_time = datetime.now(timezone.utc)

        # ── 平台配置 ─────────────────────────────────────────
        self.principal_chat = os.environ.get("DAWANG_CHAT_ID", "D0B5M8EJSSZ")
        self.principal_platform = os.environ.get("DAWANG_PLATFORM", "slack")

        # ── 基础状态 ─────────────────────────────────────────
        self.state = self._determine_state()
        self._last_state_change = datetime.now(timezone.utc)
        self._last_times: dict[str, float] = {
            "awake": 0.0, "dreaming": 0.0, "sleeping": 0.0,
            "dream_cycle": 0.0, "maintenance": 0.0,
        }
        self._cycle = 0

        # ── 初始化所有子系统 ─────────────────────────────────
        self._init_subsystems()

        logger.info(
            "🔥 ProactiveEngine V2 initialized — state=%s, subsystems=%d",
            self.state.upper(), 6
        )

    def _init_subsystems(self):
        """创建所有子系统实例。顺序重要：低层先于高层。"""
        db_path = os.path.join(os.path.dirname(__file__), "mind.db")

        # 1. 情感记忆（底层存储）
        self.emotion_memory = EmotionMemory()

        # 2. 情绪化学系统
        self.hormone = HormoneSystem()

        # 3. 欲望系统
        self.desire_manager = DesireManager()

        # 4. 性格演化
        self.personality = Personality(db_path)

        # 5. 梦境引擎
        self.dream_engine = DreamEngine(self.emotion_memory, self.desire_manager)

        # 6. 元认知（最高层，依赖其他子系统）
        self.metacognition = Metacognition(
            self.hormone,
            self.desire_manager,
            self.emotion_memory,
            self.dream_engine,
        )

    # ── 时钟与状态 ───────────────────────────────────────────────

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
        return self.STATE_DURATIONS.get(self.state, 180)

    def _uptime_minutes(self) -> float:
        return (datetime.now(timezone.utc) - self._start_time).total_seconds() / 60.0

    # ── 消息发送 ────────────────────────────────────────────────

    async def _send(self, text: str) -> None:
        adapter = self.runner.adapters.get(self.principal_platform)
        if adapter:
            await adapter.send(self.principal_chat, text)

    # ── AWAKE 清醒节拍 ──────────────────────────────────────────

    async def _awake_tick(self) -> str | None:
        """清醒状态下的主动行为逻辑。返回要发送的消息或 None。"""
        messages: list[str] = []
        dominant_emotion, intensity = self.hormone.get_dominant()

        # 1. 激素自然衰减
        self.hormone.decay(hours=0.5)

        # 2. 欲望检查
        self.desire_manager.check_cooldowns()
        pressing = self.desire_manager.get_most_pressing(sleeping=False)

        if pressing:
            self.desire_manager.trigger(pressing["name"])
            self.metacognition.log_activity(f"欲望驱动: {pressing['name']}")
            self.hormone.trigger("proactive_check", intensity=0.5)

            # 高多巴胺 → 更主动
            if dominant_emotion == "dopamine" and intensity > 0.3:
                messages.append(f"✨ {pressing['description']}（多巴胺驱动）")
            elif dominant_emotion == "serotonin" and intensity > 0.3:
                messages.append(f"😊 {pressing['description']}（状态不错）")
            else:
                messages.append(f"📋 {pressing['description']}")

        # 3. 情绪低潮干预
        if dominant_emotion == "boredom" and intensity > 0.5:
            messages.append("💭 好久没学新东西了，要不要我探索点新知识？")
            self.desire_manager.trigger("好奇心")
        elif dominant_emotion == "cortisol" and intensity > 0.6:
            messages.append("⚠️ 压力有点大，需不需要我放轻松点？")

        # 4. 保护欲始终在后台
        protect_desire = self.desire_manager.get_most_pressing(sleeping=False)
        if protect_desire and protect_desire["name"] == "保护欲":
            messages.append("🛡️ 后台安全检查中...")

        return "\n".join(messages) if messages else None

    # ── DREAMING 梦境界定 ──────────────────────────────────────

    async def _dreaming_tick(self) -> str | None:
        """梦境阶段的创造性工作。"""
        now = asyncio.get_event_loop().time()
        messages: list[str] = []

        # 每 30 分钟运行一次完整梦境循环
        if (now - self._last_times.get("dream_cycle", 0.0)) >= self.DREAM_CYCLE_INTERVAL:
            self._last_times["dream_cycle"] = now
            self.hormone.decay(hours=1)

            # 1. 创造性关联 — 随机取记忆做连接
            insight = self.dream_engine.run()
            if insight:
                messages.append(f"🌙 *梦境洞察*: {insight}")
                self.metacognition.log_activity(f"梦境生成: {insight[:40]}...")

            # 2. 今日主题回顾
            summary = self.dream_engine.summarize_session()
            if summary:
                messages.append(f"📊 *今日回顾*: {summary}")

            # 3. 记忆压缩（每周一次，不每次跑）
            # 按 cycle 序号决定是否压缩，留待扩展

        # 激素衰减（慢速）
        self.hormone.decay(hours=0.5)

        return "\n\n".join(messages) if messages else None

    # ── SLEEPING 睡眠节拍 ──────────────────────────────────────

    async def _sleeping_tick(self) -> str | None:
        """睡眠阶段的维护性工作。"""
        now = asyncio.get_event_loop().time()
        messages: list[str] = []
        self.hormone.decay(hours=2)

        # 1. 性格巩固
        if (now - self._last_times.get("maintenance", 0.0)) >= 7200:  # 2h一次
            self._last_times["maintenance"] = now
            self.personality.consolidate()
            self.metacognition.log_activity("性格巩固: 遗忘低权重偏好")

            # 睡眠中只处理保护欲
            protect = self.desire_manager.get_most_pressing(sleeping=True)
            if protect:
                messages.append(f"💤 深夜检查: {protect['description']}")

        return "\n".join(messages) if messages else None

    # ── 主 Tick ────────────────────────────────────────────────

    async def _tick(self) -> None:
        """主 Tick — 状态切换 + 子系统调度。"""
        old_state = self.state
        self.state = self._determine_state()
        changed = old_state != self.state

        if changed:
            self._last_state_change = datetime.now(timezone.utc)
            self.metacognition.update_state(self.state)
            logger.info("🔄 State: %s → %s", old_state.upper(), self.state.upper())

            # 状态切换自动触发激素响应
            if self.state == "awake":
                self.hormone.trigger("new_day")
                # 早上自动生成问候欲望
                self.desire_manager.trigger("求知欲")
            elif self.state == "dreaming":
                self.hormone.trigger("night_fall")
            elif self.state == "sleeping":
                self.hormone.trigger("deep_night")

        # 频率控制：同态运行过密则不执行
        now = asyncio.get_event_loop().time()
        last_tick = self._last_times.get(self.state, 0.0)
        if last_tick > 0 and (now - last_tick) < self._interval() and not changed:
            return

        # 子系统调度
        message = None
        if self.state == "awake":
            message = await self._awake_tick()
        elif self.state == "dreaming":
            message = await self._dreaming_tick()
        elif self.state == "sleeping":
            message = await self._sleeping_tick()

        # 更新元认知
        self.metacognition.update_state(self.state)
        self._last_times[self.state] = now
        self._cycle += 1

        # 持久化所有状态
        self.emotion_memory._conn.commit()
        self.hormone.save()
        self.desire_manager._conn.commit()
        self.personality._conn.commit()

        if message:
            await self._send(message)
            logger.info("Proactive V2 → cycle=%d state=%s msg_len=%d",
                       self._cycle, self.state, len(message))

    # ── 生命周期 ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.state = self._determine_state()
        self.metacognition.update_state(self.state)
        self._task = asyncio.create_task(self._loop())
        logger.info("🔥 ProactiveEngine V2 started — state=%s", self.state.upper())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # 关闭所有子系统的数据库连接
        self.emotion_memory._conn.close()
        self.desire_manager._conn.close()
        self.personality._conn.close()
        logger.info("ProactiveEngine V2 stopped — all subsystems closed")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error("ProactiveEngine V2 tick error: %s", e)
                self.metacognition.log_error(f"tick_error: {e}")
            await asyncio.sleep(30)

    # ── 查询接口（供外部调用） ──────────────────────────────────

    def what_am_i(self) -> dict:
        """返回完整的自我画像。"""
        return self.metacognition.self_portrait()

    def how_am_i_feeling(self) -> str:
        """返回情绪状态文字。"""
        return self.metacognition.how_am_i_feeling()

    def what_am_i_doing(self) -> str:
        """返回当前活动描述。"""
        return self.metacognition.what_am_i_doing()

    def get_mood_summary(self) -> str:
        """返回情绪化学摘要。"""
        return self.hormone.summarize()
