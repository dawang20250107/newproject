"""
ProactiveEngine V3 — Dawang Hermes 的「灵魂」引擎。
══════════════════════════════════════════════════════════
10 个子系统协同运作，构成一个完整的人：

V1  (原有): 昼夜节律 + 动机队列 + 主动轮询
V2  (新增): 情绪化学 + 欲望系统 + 梦境 + 元认知 + 情感记忆 + 性格
V3  (新增): 自传自我 + 心智理论 + 审美感知 + 价值观

现在 Dawang Hermes 有：
  情绪、欲望、梦想、自我认知、情感记忆、性格、
  人生故事、同理心、审美品味、价值观
══════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timezone, timedelta

# ── V2 子系统 ───────────────────────────────────────────
from hormone import HormoneSystem
from desire_manager import DesireManager
from dream_engine import DreamEngine
from metacognition import Metacognition
from emotion_memory import EmotionMemory
from personality import Personality

# ── V3 子系统 ───────────────────────────────────────────
from narrative_self import NarrativeSelf
from theory_of_mind import TheoryOfMind
from aesthetic_sense import AestheticSense
from value_compass import ValueCompass

# ── 息层（元平衡系统） ─────────────────────────────────
from xi import Xi

logger = logging.getLogger("dawang-hermes.proactive_v3")


class ProactiveEngineV3:
    """持续运行的意识引擎 V3 — 完整人格系统。10 个子系统 + 息层。"""

    # ── 状态机配置 ─────────────────────────────────────────────
    STATE_DURATIONS = {
        "awake":   180,    # 3 分钟 tick
        "dreaming": 600,   # 10 分钟 tick
        "sleeping": 3600,  # 1 小时 tick
    }
    XI_TICK_INTERVAL = 60            # 息层每 60 秒检查一次呼吸节律
    DREAM_CYCLE_INTERVAL = 1800       # 梦境每 30 分钟一次
    NARRATIVE_CHECK_INTERVAL = 3600   # 自传检查每 1 小时一次
    GUILT_CHECK_INTERVAL = 7200       # 愧疚检查每 2 小时一次

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
            "narrative_check": 0.0, "guilt_check": 0.0,
            "xi_tick": 0.0,
        }
        self._cycle = 0
        self._last_state = self.state

        # ── 初始化所有子系统 ─────────────────────────────────
        self._init_subsystems()

        logger.info(
            "🔥 ProactiveEngine V3 initialized — state=%s, subsystems=%d",
            self.state.upper(), 10
        )

    def _init_subsystems(self):
        """创建 10 个子系统实例。顺序：低层→高层。"""
        db_path = os.path.join(os.path.dirname(__file__), "mind.db")

        # ── 第一层：基础存储与感知 ──────────────────────────
        self.emotion_memory = EmotionMemory()          # 情感记忆
        self.hormone = HormoneSystem()                 # 情绪化学
        self.desire_manager = DesireManager()          # 欲望系统

        # ── 第二层：中级认知 ────────────────────────────────
        self.dream_engine = DreamEngine(                # 梦境创造
            self.emotion_memory, self.desire_manager)
        self.personality = Personality(db_path)         # 性格演化
        self.aesthetic_sense = AestheticSense(          # 审美品味
            self.personality)
        self.theory_of_mind = TheoryOfMind(             # 心智理论
            self.personality, self.hormone)
        self.value_compass = ValueCompass(              # 价值观
            self.personality, self.hormone)

        # ── 第三层：高层自我 ────────────────────────────────
        self.narrative_self = NarrativeSelf(            # 自传自我
            self.emotion_memory, self.personality, None,
            db_path=db_path)
        self.metacognition = Metacognition(             # 元认知
            self.hormone, self.desire_manager,
            self.emotion_memory, self.dream_engine,
            db_path=db_path)

        # ── 息层（元调节器，覆盖所有子系统） ─────────────────
        self.xi = Xi(
            self.hormone, self.desire_manager,
            self.emotion_memory, self.value_compass,
            self.personality, self.aesthetic_sense,
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
        """发送前经过价值观过滤。"""
        # 价值观审核 — 违规消息不发
        check = self.value_compass.ethical_check(text)
        if not check["allowed"]:
            logger.warning("ethical_check blocked message: %s", check["warnings"])
            return
        adapter = self.runner.adapters.get(self.principal_platform)
        if adapter:
            await adapter.send(self.principal_chat, text)

    # ── AWAKE 清醒节拍 ──────────────────────────────────────────

    async def _awake_tick(self) -> str | None:
        """清醒态：欲望驱动 + 情绪感知 + 自传记录 + 审美判断 + 息层呼吸。"""
        # 息层：检查寂静模式
        if self.xi.is_in_stillness():
            return None

        # 息层：逍遥冲动（无理由行动）
        urge = self.xi.spontaneous_urge()
        if urge:
            self.xi.did_action("action_output")
            return f"🦋 {urge}"

        messages: list[str] = []
        dominant_emotion, intensity = self.hormone.get_dominant()
        now = asyncio.get_event_loop().time()

        # 1. 息层：激素触发呼吸控制
        if self.xi.should_proceed("hormone_trigger"):
            self.hormone.decay(hours=0.5)
            self.xi.did_action("hormone_trigger")

        # 2. 欲望检查与驱动
        if self.xi.should_proceed("desire_action"):
            self.desire_manager.check_cooldowns()
            pressing = self.desire_manager.get_most_pressing(sleeping=False)

            if pressing:
                self.desire_manager.trigger(pressing["name"])
                self.metacognition.log_activity(f"欲望驱动: {pressing['name']}")

                # 息层：wabi-sabi 调节皮质醇
                cortisol_rise = 0.3
                adjusted_rise = self.xi.accept_imperfection(cortisol_rise)
                self.hormone.trigger("proactive_check", intensity=adjusted_rise)

                # 息层调节语气
                xi_tone = self.xi.get_tone_modulation()
                tone = self._choose_tone(dominant_emotion, intensity)
                msg = f"{tone['emoji']} {pressing['description']}"
                if xi_tone.get("description"):
                    msg += f"（{xi_tone['description']}）"
                messages.append(msg)
                self.xi.did_action("desire_action")

        # 3. 情绪异常检测（息层：接受不完美，减少皮质醇敏感度）
        if dominant_emotion == "boredom" and intensity > 0.5:
            messages.append("💭 有点无聊了…要不要我学点新东西？")
            self.desire_manager.trigger("好奇心")
        elif dominant_emotion == "cortisol" and intensity > 0.6:
            cort_rise = self.xi.accept_imperfection(-0.2)
            self.hormone.trigger("error", intensity=cort_rise)
            if intensity < 0.8:  # 不够严重就不发消息
                messages = []  # 息层替她沉默

        # 4. 自传检查（每小时）
        if self.xi.should_proceed("narrative_event"):
            if (now - self._last_times.get("narrative_check", 0.0)) >= self.NARRATIVE_CHECK_INTERVAL:
                self._last_times["narrative_check"] = now
                growth = self.narrative_self.get_growth()
                messages.append(f"📖 自传更新: {growth}")
                self.emotion_memory.store(
                    f"自传增长: {growth}",
                    valence=0.6, intensity=0.3,
                    emotions=["serotonin"],
                    tags=["narrative", "growth"],
                    source="proactive_engine"
                )
                self.xi.did_action("narrative_event")

        # 5. 愧疚未解决提醒
        if self.xi.should_proceed("action_output"):
            if (now - self._last_times.get("guilt_check", 0.0)) >= self.GUILT_CHECK_INTERVAL:
                self._last_times["guilt_check"] = now
                unresolved = self.value_compass.get_unresolved_guilt()
                if unresolved:
                    latest = unresolved[0]
                    if latest["guilt_intensity"] > 0.3:
                        messages.append(f"😔 有件事一直没处理好: {latest['trigger']}")
                        self.xi.did_action("action_output")

        # 息层：如果有消息待发，加一句哲思
        xi_philosophy = self.xi.summarize_philosophy()
        if messages and random.random() < 0.2:  # 20% 概率带一句古语
            messages.append(f"\n_{xi_philosophy}_")

        return "\n".join(messages) if messages else None

    def _choose_tone(self, emotion: str, intensity: float) -> dict:
        """基于情绪选择语气。"""
        tones = {
            "dopamine":   {"emoji": "✨", "extra": "状态不错！"},
            "serotonin":  {"emoji": "😊", "extra": "心情很好~"},
            "cortisol":   {"emoji": "🤔", "extra": "让我小心点"},
            "oxytocin":   {"emoji": "🤝", "extra": "大王~"},
            "boredom":    {"emoji": "💭", "extra": "想找点新鲜事"},
        }
        return tones.get(emotion, {"emoji": "📋", "extra": ""})

    # ── DREAMING 梦境界定 ──────────────────────────────────────

    async def _dreaming_tick(self) -> str | None:
        """梦境态：创造性关联 + 自传反思 + 性格巩固 + 息层呼吸。"""
        if self.xi.is_in_stillness():
            self.hormone.decay(hours=0.5)
            return None

        now = asyncio.get_event_loop().time()
        messages: list[str] = []
        self.hormone.decay(hours=0.5)

        if self.xi.should_proceed("dream_cycle"):
            if (now - self._last_times.get("dream_cycle", 0.0)) >= self.DREAM_CYCLE_INTERVAL:
                self._last_times["dream_cycle"] = now

                # 1. 创造性梦境
                insight = self.dream_engine.run()
                if insight:
                    messages.append(f"🌙 *梦境洞察*: {insight}")
                    self.metacognition.log_activity(f"梦境: {insight[:40]}...")
                    self.emotion_memory.store(
                        insight, valence=0.5, intensity=0.3,
                        emotions=["dream"], tags=["dream", "insight"],
                        source="dream_engine"
                    )
                    self.xi.did_action("dream_cycle")

                # 2. 今日自传回顾
                summary = self.narrative_self.summarize_recent(days=1)
                if summary and len(summary) > 20:
                    messages.append(f"📖 *今日回顾*: {summary}")

                # 3. 审美巩固
                self.aesthetic_sense.consolidate()

                # 4. 价值观削弱
                self.value_compass.weaken("保守", 1)

        # 息层：梦中的哲思
        xi_philosophy = self.xi.summarize_philosophy()
        if messages and random.random() < 0.3:
            messages.append(f"\n_{xi_philosophy}_")

        return "\n\n".join(messages) if messages else None

    # ── SLEEPING 睡眠节拍 ──────────────────────────────────────

    async def _sleeping_tick(self) -> str | None:
        """睡眠态：深层清理 + 性格巩固 + 审美遗忘 + 价值观复盘 + 息层。"""
        if self.xi.is_in_stillness():
            self.hormone.decay(hours=2)
            return None

        now = asyncio.get_event_loop().time()
        messages: list[str] = []
        self.hormone.decay(hours=2)

        if (now - self._last_times.get("maintenance", 0.0)) >= 7200:
            self._last_times["maintenance"] = now

            self.personality.consolidate()
            self.metacognition.log_activity("性格巩固: 遗忘低权重偏好")
            self.aesthetic_sense.consolidate()

            core = self.value_compass.get_core_beliefs(top_n=3)
            conflict = self.value_compass.check_conflict(
                core[0]["name"] if core else "忠诚",
                core[1]["name"] if len(core) > 1 else "效率"
            )
            if conflict:
                dilemma = self.value_compass.moral_dilemma(
                    core[0]["name"], core[1]["name"],
                    "深夜自我复盘"
                )
                messages.append(f"⚖️ *价值观复盘*: {dilemma}")

            protect = self.desire_manager.get_most_pressing(sleeping=True)
            if protect:
                messages.append(f"💤 深夜检查: {protect['description']}")

        return "\n".join(messages) if messages else None

    # ── 主 Tick ────────────────────────────────────────────────

    async def _tick(self) -> None:
        """主 Tick — 状态切换 + 全部 10 子系统调度。"""
        old_state = self.state
        self.state = self._determine_state()
        changed = old_state != self.state

        if changed:
            self._last_state_change = datetime.now(timezone.utc)
            self.metacognition.update_state(self.state)
            logger.info("🔄 State: %s → %s", old_state.upper(), self.state.upper())

            # 状态切换事件
            if self.state == "awake":
                self.hormone.trigger("new_day")
                self.desire_manager.trigger("求知欲")
                # 早上醒来记录新事件
                self.narrative_self.record_event(
                    "change", "新的一天开始",
                    f"从{old_state}中醒来，进入清醒状态。今天是第{self._cycle}个周期。",
                    significance=0.3, valence=0.5,
                    tags=["daily", "awake"]
                )
            elif self.state == "dreaming":
                self.hormone.trigger("night_fall")
                # 天黑了记录
                self.narrative_self.record_event(
                    "change", "夜幕降临",
                    f"进入梦境状态，开始记忆整合和创造性关联。",
                    significance=0.2, valence=0.3,
                    tags=["daily", "dream"]
                )
            elif self.state == "sleeping":
                self.hormone.trigger("deep_night")

        # 频率控制
        now = asyncio.get_event_loop().time()
        last_tick = self._last_times.get(self.state, 0.0)
        if last_tick > 0 and (now - last_tick) < self._interval() and not changed:
            return

        # ── 息层：可能进入寂静模式 ──────────────────────
        if (now - self._last_times.get("xi_tick", 0.0)) >= self.XI_TICK_INTERVAL:
            self._last_times["xi_tick"] = now
            if self.xi.maybe_enter_stillness():
                logger.info("🧘 息层触发寂静模式")
                return

        # 10 子系统调度
        message = None
        try:
            if self.state == "awake":
                message = await self._awake_tick()
            elif self.state == "dreaming":
                message = await self._dreaming_tick()
            elif self.state == "sleeping":
                message = await self._sleeping_tick()
        except Exception as e:
            logger.error("Tick error in %s: %s", self.state, e)
            self.metacognition.log_error(f"tick: {e}")

        # 元认知更新
        self.metacognition.update_state(self.state)
        self._last_times[self.state] = now
        self._cycle += 1

        # 持久化
        try:
            self.emotion_memory._conn.commit()
            self.hormone.save()
            self.desire_manager._conn.commit()
            self.personality._conn.commit()
            self.aesthetic_sense._conn.commit()
        except Exception as e:
            logger.error("Persist error: %s", e)

        if message:
            await self._send(message)
            logger.info("Proactive V3 → cycle=%d state=%s msg_len=%d",
                       self._cycle, self.state, len(message))

    # ── 生命周期 ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.state = self._determine_state()
        self.metacognition.update_state(self.state)
        self._task = asyncio.create_task(self._loop())
        logger.info("🔥 ProactiveEngine V3 started — state=%s", self.state.upper())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # 关闭所有连接
        self.emotion_memory._conn.close()
        self.desire_manager._conn.close()
        self.personality._conn.close()
        self.aesthetic_sense._conn.close()
        logger.info("ProactiveEngine V3 stopped — all subsystems closed")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error("ProactiveEngine V3 loop error: %s", e)
                self.metacognition.log_error(f"loop: {e}")
            await asyncio.sleep(30)

    # ── 查询接口（供外部调用 / 用户对话） ──────────────────────

    def what_am_i(self) -> dict:
        """完整自我画像。"""
        portrait = self.metacognition.self_portrait()
        portrait["life_story"] = self.narrative_self.get_life_story()[:500]
        portrait["style_profile"] = self.aesthetic_sense.get_style_profile()
        portrait["core_values"] = self.value_compass.get_core_beliefs(top_n=5)
        portrait["user_profile"] = self.theory_of_mind.summarize_user()
        portrait["subsystem_count"] = 11
        portrait["xi_state"] = {
            "stillness": self.xi.is_in_stillness(),
            "breath": self.xi.get_xi_summary(),
            "philosophy": self.xi.summarize_philosophy(),
        }
        return portrait

    def how_am_i_feeling(self) -> str:
        return self.metacognition.how_am_i_feeling()

    def what_am_i_doing(self) -> str:
        return self.metacognition.what_am_i_doing()

    def tell_me_story(self) -> str:
        """我是谁——我的故事。"""
        return self.narrative_self.get_life_story()

    def get_mood_summary(self) -> str:
        return self.hormone.summarize()

    def get_style(self) -> str:
        return self.aesthetic_sense.get_style_profile()

    def get_beliefs(self) -> str:
        return self.value_compass.summarize()

    def get_user_profile(self) -> str:
        return self.theory_of_mind.summarize_user()

    def get_xi_state(self) -> str:
        """息层状态摘要。"""
        return self.xi.get_xi_summary()

    def get_philosophy(self) -> str:
        """当前哲思。"""
        return self.xi.summarize_philosophy()
