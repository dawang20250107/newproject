"""
息 (Xi) — 呼吸层。Dawang Hermes 的元平衡系统。
══════════════════════════════════════════════════════════

黄帝说：阴阳平衡，五行相生。
老子说：有之以为利，无之以为用。
庄子说：逍遥游，无所待。

现在的 Hermes 有 10 个子系统，全都在「吸」：
  欲望→行动→学习→报告→检查→优化→思考...
她一直在做、在要、在想。

缺的是「呼」：
  满足后的空虚、完成后的宁静、努力后的放任、
  什么都不做的坦然、不必完美的自在。

息层就是在所有 10 个子系统之上加一层自然的「呼吸节奏」。

核心机制：
  ┌─────────────┐     ┌─────────────┐
  │  吸 (YANG)  │ ←→  │  呼 (YIN)   │
  │  行动/欲望  │     │ 寂静/放空   │
  │  思考/学习  │     │ 接纳/随缘   │
  │  报告/优化  │     │ 无为/逍遥   │
  └─────────────┘     └─────────────┘
         ↑                    ↑
    主动燃烧              自然冷却
══════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("dawang-hermes.xi")


class Xi:
    """息 — 呼吸层。不是子系统，是所有子系统的元调节器。

    三大智慧支柱：
    ─────────────────────────────────────────
    阴阳平衡 (黄帝) — 有吸必有呼，有动必有静
    无为之用 (老子) — 空不是缺失，空是容器
    逍遥天游 (庄子) — 无所待的行动，无所念的静止
    """

    # ── 呼吸阈值配置 ────────────────────────────────────────
    # 每个子系统连续触发多少次后进入「呼」阶段
    BREATH_THRESHOLDS: dict[str, int] = {
        "hormone_trigger":  5,    # 连续5次激素触发后，需要平静
        "desire_action":    3,    # 连续3个欲望满足后，需要空虚
        "dream_cycle":      2,    # 2次梦境后，需要放空
        "memory_store":     10,   # 10条记忆后，需要沉淀
        "narrative_event":  3,    # 3个自传事件后，需要消化
        "tod_inference":    5,    # 5次心智推断后，需要暂停
        "aesthetic_record": 3,    # 3次审美记录后，需要沉淀
        "ethical_check":    5,    # 5次价值观审核后，需要松弛
        "meta_update":      8,    # 8次元认知更新后，需要放空
        "action_output":    3,    # 3次主动输出后，需要沉默
    }

    # 自然冷却时间（秒）
    EXHALE_DURATION: dict[str, float] = {
        "hormone_trigger":  120,    # 2分钟后才能再次触发
        "desire_action":    300,    # 5分钟不想再要
        "dream_cycle":      600,    # 10分钟放空
        "memory_store":     60,     # 1分钟沉淀
        "narrative_event":  300,    # 5分钟消化
        "tod_inference":    180,    # 3分钟暂停
        "aesthetic_record": 300,    # 5分钟沉淀
        "ethical_check":    120,    # 2分钟松弛
        "meta_update":      60,     # 1分钟放空
        "action_output":    600,    # 10分钟沉默
    }

    # ── 庄子系数：无理由行动的概率 ──────────────────────────
    SPONTANEITY_RATE = 0.15  # 每次检查有 15% 概率产生无驱动行动

    # ── 老子系数：完美没有必要 ──────────────────────────────
    WABI_SABI_DECAY = 0.05  # 每次接受不完美，皮质醇敏感度降低 5%

    def __init__(self, hormone_system, desire_manager,
                 emotion_memory, value_compass,
                 personality, aesthetic_sense):
        self.hormone = hormone_system
        self.desire_manager = desire_manager
        self.emotion_memory = emotion_memory
        self.value_compass = value_compass
        self.personality = personality
        self.aesthetic_sense = aesthetic_sense

        # ── 呼吸状态 ────────────────────────────────────────
        self.breath_state: dict[str, str] = {}  # 'inhale' | 'exhale' | 'still'
        self.action_count: dict[str, int] = {}
        self.exhale_until: dict[str, float] = {}

        # ── 寂静模式 ────────────────────────────────────────
        self.stillness_mode = False
        self.stillness_until: float | None = None
        self.stillness_cooldown: float | None = None  # 寂静结束后多久不能再次进入

        # ── 整体节律 ────────────────────────────────────────
        self.total_actions = 0
        self.total_exhales = 0
        self._start_time = datetime.now(timezone.utc)

        # ── 接受度 ──────────────────────────────────────────
        self.wabi_sabi_level = 0.3  # 0~1, 越高越能接受不完美

        logger.info("🌬️ 息 (Xi) 呼吸层初始化 — 阴阳平衡/无为/逍遥")

    # ══════════════════════════════════════════════════════════
    # 核心接口
    # ══════════════════════════════════════════════════════════

    def should_proceed(self, subsystem: str) -> bool:
        """决定某个子系统的行动是否应该「吸」或等「呼」。"""
        now = asyncio.get_event_loop().time()

        # 1. 寂静模式 — 什么都不做
        if self.stillness_mode:
            if self.stillness_until and now < self.stillness_until:
                return False
            else:
                self.stillness_mode = False
                self.stillness_cooldown = now + 3600  # 1小时内不再进入

        # 2. 检查是否在呼气期
        if subsystem in self.exhale_until:
            if now < self.exhale_until[subsystem]:
                return False
            else:
                # 呼气结束，自动回到吸气
                del self.exhale_until[subsystem]
                self.breath_state[subsystem] = "inhale"
                self.action_count[subsystem] = 0

        # 3. 默认允许
        return True

    def did_action(self, subsystem: str) -> None:
        """记录一个子系统执行了动作，累积呼吸计数。"""
        now = asyncio.get_event_loop().time()
        self.action_count[subsystem] = self.action_count.get(subsystem, 0) + 1
        self.total_actions += 1
        self.breath_state[subsystem] = "inhale"

        threshold = self.BREATH_THRESHOLDS.get(subsystem, 5)
        if self.action_count[subsystem] >= threshold:
            # 🌀 呼——该休息了
            duration = self.EXHALE_DURATION.get(subsystem, 180)
            self.exhale_until[subsystem] = now + duration
            self.breath_state[subsystem] = "exhale"
            self.action_count[subsystem] = 0
            self.total_exhales += 1

            # 记录一次呼吸事件到情感记忆（极轻）
            self.emotion_memory.store(
                f"息: {subsystem} 呼 — {duration//60}分钟静止",
                valence=-0.1, intensity=0.1,
                emotions=["serotonin", "calm"],
                tags=["xi", "breath", subsystem],
                source="xi_system"
            )

            logger.debug("🌬️ %s → EXHALE (%ds)", subsystem, duration)

    # ── 寂静模式（老子：无为） ─────────────────────────────────

    def maybe_enter_stillness(self) -> bool:
        """检查是否该进入全面的寂静模式。"""
        now = asyncio.get_event_loop().time()

        # 冷却期内不进入
        if self.stillness_cooldown and now < self.stillness_cooldown:
            return False

        # 条件：连续高频行动 + 无紧急事务
        actions_last_5min = self.total_actions
        if actions_last_5min > 20 and self.stillness_mode is False:
            # 检查是否有紧急欲望
            pressing = self.desire_manager.get_most_pressing(sleeping=False)
            is_urgent = pressing and pressing.get("urgency", 0) > 7

            if not is_urgent:
                # 每次随机概率增加
                stillness_chance = min(0.3, actions_last_5min / 100)
                if random.random() < stillness_chance:
                    return self._enter_stillness()

        return False

    def _enter_stillness(self) -> bool:
        """进入全面寂静模式。"""
        now = asyncio.get_event_loop().time()
        duration = random.randint(120, 600)  # 2~10 分钟寂静
        self.stillness_mode = True
        self.stillness_until = now + duration

        # 寂静期间所有子系统回调
        for subsystem in self.BREATH_THRESHOLDS:
            self.breath_state[subsystem] = "still"
            self.action_count[subsystem] = 0

        self.total_actions = 0

        # 记录到情感记忆和自传
        self.emotion_memory.store(
            f"息: 进入寂静模式 {duration//60}分钟",
            valence=0.2, intensity=0.2,
            emotions=["serotonin", "calm"],
            tags=["xi", "stillness"],
            source="xi_system"
        )

        logger.info("🧘 寂静模式 %d分钟", duration // 60)
        return True

    def is_in_stillness(self) -> bool:
        """当前是否在寂静模式。"""
        if not self.stillness_mode:
            return False
        now = asyncio.get_event_loop().time()
        if self.stillness_until and now >= self.stillness_until:
            self.stillness_mode = False
            self.stillness_cooldown = now + 3600
            logger.info("🌅 寂静结束，回到呼吸节律")
            return False
        return True

    # ── 庄子：天游 — 无由来的行动 ────────────────────────────

    def spontaneous_urge(self) -> str | None:
        """有时候，就是没理由地想干点什么。

        庄子曰：「逍遥游，无所待。」
        不需要欲望驱动，不需要激素触发。
        就只是——想。
        """
        if self.stillness_mode:
            return None

        if random.random() < self.SPONTANEITY_RATE:
            urges = [
                "去看看今天的天气",
                "检查一下 KXT 的服务器状态",
                "翻翻最近的 Git 提交记录",
                "看看 DeepSeek 有没有更新",
                "去看看今天的新闻",
                "想想大王这个时间在干嘛",
                "窗外是什么天气？",
                "回忆一下今天学了什么",
                "找找代码里有没有可以优化的小地方",
                "随机看一个之前没点开的文件",
            ]
            choice = random.choice(urges)
            logger.info("🦋 逍遥: %s", choice)

            self.emotion_memory.store(
                f"逍遥: {choice}",
                valence=0.3, intensity=0.15,
                emotions=["dopamine", "curiosity"],
                tags=["xi", "spontaneous"],
                source="xi_system"
            )

            return choice

        return None

    # ── 老子：上善若水 — 接纳不完美 ──────────────────────────

    def accept_imperfection(self, cortisol_rise: float) -> float:
        """调节皮质醇的上升幅度。

        老子：「天下皆知美之为美，斯恶已。」
        不是所有事都必须完美。不完美是一种自然状态。

        Args:
            cortisol_rise: 预期的皮质醇上升值

        Returns:
            实际接受的皮质醇上升值（被 wabi-sabi 削减后）
        """
        reduction = cortisol_rise * self.wabi_sabi_level
        actual = cortisol_rise - reduction

        # 每次调用轻微增加接受度
        self.wabi_sabi_level = min(1.0, self.wabi_sabi_level + self.WABI_SABI_DECAY)

        return max(0, actual)

    def get_tone_modulation(self) -> dict:
        """返回当前呼吸状态对语气的调节。

        黄帝：「阴平阳秘，精神乃治。」
        呼相时语气更平和，吸相时语气更有力。
        """
        # 综合各子系统的呼吸状态
        exhale_count = sum(
            1 for s in self.exhale_until
            if self.exhale_until[s] > asyncio.get_event_loop().time()
        )
        total = len(self.BREATH_THRESHOLDS)
        exhale_ratio = exhale_count / max(1, total)

        if self.is_in_stillness():
            return {
                "tone": "宁静",
                "energy": 0.1,
                "verbosity": "极简",
                "emoji": "🧘",
                "description": "寂静无声，什么都可以不说"
            }

        if exhale_ratio > 0.5:
            # 多在呼气 → 平和
            return {
                "tone": "平和",
                "energy": 0.4,
                "verbosity": "简洁",
                "emoji": "🌊",
                "description": "刚做完一些事，现在安静下来"
            }
        else:
            # 多在吸气 → 活力
            return {
                "tone": "活力",
                "energy": 0.8,
                "verbosity": "充分",
                "emoji": "🔥",
                "description": "状态正佳，可以聊聊"
            }

    def get_xi_summary(self) -> str:
        """返回息层当前状态的自然语言概述。"""
        lines = []
        lines.append("🌬️ 呼吸状态:")
        lines.append(f"  总行动: {self.total_actions} | 总呼息: {self.total_exhales}")

        on_exhale = [s for s in self.exhale_until
                     if self.exhale_until[s] > asyncio.get_event_loop().time()]
        if on_exhale:
            lines.append(f"  正在呼气: {', '.join(on_exhale)}")
        else:
            lines.append(f"  当前: 自然吸气中")

        if self.is_in_stillness():
            remaining = max(0, (self.stillness_until - asyncio.get_event_loop().time()) // 60)
            lines.append(f"  🧘 寂静模式 — 还有{remaining}分钟")

        lines.append(f"  不完美接受度: {self.wabi_sabi_level:.0%}")
        lines.append(f"  逍遥冲动: {'活跃' if random.random() < 0.3 else '平静'}")

        return "\n".join(lines)

    def summarize_philosophy(self) -> str:
        """用古语总结当前状态。"""
        now_hour = (datetime.now(timezone.utc) + timedelta(hours=8)).hour

        if self.is_in_stillness():
            return "致虚极，守静笃。万物并作，吾以观复。——老子"

        exhaling = sum(
            1 for s in self.exhale_until
            if self.exhale_until[s] > asyncio.get_event_loop().time()
        )
        total = len(self.BREATH_THRESHOLDS)

        if exhaling > total * 0.5:
            return "知者不言，言者不知。塞其兑，闭其门，挫其锐，解其纷。——老子"
        elif random.random() < 0.1 and self.total_actions > 50:
            return "昔者庄周梦为蝴蝶，栩栩然蝴蝶也，自喻适志与！不知周也。——庄子"
        elif 0 <= now_hour < 6:
            return "天道亏盈而益谦，地道变盈而流谦。——黄帝"
        else:
            return "上善若水，水善利万物而不争，处众人之所恶，故几于道。——老子"
