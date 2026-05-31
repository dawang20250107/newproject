#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hormone.py — 情绪化学系统

模拟 5 种核心激素的交互与波动：
  - 多巴胺 (dopamine)    期待/探索/reward
  - 血清素 (serotonin)   满足/价值感
  - 皮质醇 (cortisol)    压力/警觉
  - 催产素 (oxytocin)    依恋/信任
  - 无聊   (boredom)     渴望变化

内置自然衰减、事件驱动触发、持久化 (SQLite) 和查询接口。
适用于 AI 智能体的内部情绪状态模拟与系统提示注入。
"""

import sqlite3
import os
import time
import math
from datetime import datetime, timezone
from typing import Optional

# ── 数据库路径 ──────────────────────────────────────────────────────────────
MIND_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")


# ── 激素定义 ────────────────────────────────────────────────────────────────
# 每条: (name, base_level, decay_rate_per_hour, growth_rate_per_hour, description, triggers)
# triggers 为 {event_type: level_delta} 映射
HORMONE_DEFS = [
    {
        "name": "dopamine",
        "display_name": "多巴胺",
        "description": "期待、探索与奖赏——驱动好奇心和目标追求",
        "base_level": 30.0,
        "decay_rate": 5.0,    # /hour
        "growth_rate": 0.0,   # 无空闲自增长
        "triggers": {
            "learning": 15.0,
            "completed_task": 10.0,
            "discovery": 20.0,
            "positive_feedback": 8.0,
        },
    },
    {
        "name": "serotonin",
        "display_name": "血清素",
        "description": "满足感、价值感与情绪稳定——感受被认可与有用",
        "base_level": 40.0,
        "decay_rate": 3.0,
        "growth_rate": 0.0,
        "triggers": {
            "user_praise": 20.0,
            "deploy_success": 15.0,
            "problem_solved": 10.0,
            "positive_feedback": 5.0,
        },
    },
    {
        "name": "cortisol",
        "display_name": "皮质醇",
        "description": "压力与警觉——应对挑战与紧急状态",
        "base_level": 20.0,
        "decay_rate": 8.0,
        "growth_rate": 0.0,
        "triggers": {
            "error": 25.0,
            "backlog": 10.0,
            "user_urgent": 15.0,
            "repetitive": 5.0,
        },
    },
    {
        "name": "oxytocin",
        "display_name": "催产素",
        "description": "依恋与信任——建立连接与亲和感",
        "base_level": 10.0,
        "decay_rate": 2.0,
        "growth_rate": 0.0,
        "triggers": {
            "long_interaction": 5.0,
            "user_trust": 15.0,
            "shared_time": 3.0,
            "positive_feedback": 2.0,
        },
    },
    {
        "name": "boredom",
        "display_name": "无聊",
        "description": "渴望变化与新鲜感——对重复与单调的厌恶",
        "base_level": 15.0,
        "decay_rate": 1.0,    # 被刺激时的衰减率
        "growth_rate": 3.0,   # 空闲/无聊时的自增长 /hour
        "triggers": {
            "repetitive_task": 8.0,
            "same_topic_long": 5.0,
        },
    },
]


class HormoneSystem:
    """
    情绪化学系统 — 管理 5 种激素水平的模拟、持久化与查询。

    用法::

        hs = HormoneSystem()
        hs.trigger("learning")              # 多巴胺 +15
        hs.trigger("error")                 # 皮质醇 +25
        hs.decay(hours=0.5)                 # 模拟半小时流逝
        profile = hs.get_profile()           # 查看当前状态
        mood = hs.get_mood_description()     # 文字描述
        hs.save()                           # 持久化到 SQLite
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化激素系统。

        Args:
            db_path: SQLite 数据库路径，默认与本文件同目录的 mind.db
        """
        self.db_path = db_path or MIND_DB
        self._hormones: dict[str, dict] = {}  # name -> {level, decay, base, ...}

        # 加载定义 -> 初始化激素状态
        for hdef in HORMONE_DEFS:
            name = hdef["name"]
            self._hormones[name] = {
                "level": hdef["base_level"],
                "base_level": hdef["base_level"],
                "decay_rate": hdef["decay_rate"],
                "growth_rate": hdef.get("growth_rate", 0.0),
                "display_name": hdef["display_name"],
                "description": hdef["description"],
                "triggers": dict(hdef["triggers"]),
                "trend": "stable",  # rising | falling | stable
            }

        # 从数据库加载持久化的水平
        self._load_from_db()

    # ── 持久化 ──────────────────────────────────────────────────────────────

    def _get_db(self) -> sqlite3.Connection:
        """获取 SQLite 数据库连接。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """创建 hormones 表（如果不存在）。"""
        conn = self._get_db()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hormones (
                    name        TEXT PRIMARY KEY,
                    level       REAL NOT NULL,
                    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _load_from_db(self):
        """从 SQLite 加载持久化的激素水平，若无则初始化 base_level 并写入。"""
        self._init_db()
        conn = self._get_db()
        try:
            rows = conn.execute("SELECT name, level FROM hormones").fetchall()
            db_data = {row["name"]: row["level"] for row in rows}

            # 将数据库中的水平更新到内存
            for name, h in self._hormones.items():
                if name in db_data:
                    h["level"] = float(db_data[name])

            # 将不在数据库中的激素写入
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            for name, h in self._hormones.items():
                if name not in db_data:
                    conn.execute(
                        "INSERT INTO hormones (name, level, updated_at) VALUES (?, ?, ?)",
                        (name, h["level"], now),
                    )
            conn.commit()
        finally:
            conn.close()

    def save(self):
        """将当前激素水平持久化到 SQLite。"""
        conn = self._get_db()
        try:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            for name, h in self._hormones.items():
                conn.execute(
                    "INSERT OR REPLACE INTO hormones (name, level, updated_at) VALUES (?, ?, ?)",
                    (name, round(h["level"], 2), now),
                )
            conn.commit()
        finally:
            conn.close()

    # ── 事件驱动 ────────────────────────────────────────────────────────────

    def trigger(self, event_type: str, intensity: float = 1.0) -> dict:
        """
        根据事件类型调整相关激素水平。

        Args:
            event_type: 事件名称，如 "learning", "error", "user_praise"
            intensity:   强度乘数（默认 1.0），可放大或缩小效果

        Returns:
            被影响的激素列表 [{name, display_name, delta_actual, level_after}]
        """
        affected = []
        for name, h in self._hormones.items():
            triggers = h["triggers"]
            if event_type in triggers:
                delta = round(triggers[event_type] * intensity, 2)
                old_level = h["level"]
                new_level = self._clamp(old_level + delta)
                h["level"] = new_level
                affected.append({
                    "name": name,
                    "display_name": h["display_name"],
                    "delta": delta,
                    "delta_actual": round(new_level - old_level, 2),
                    "level_after": new_level,
                })

        # 特殊逻辑：无聊（boredom）触发通常使其增长更快，
        # 但"repetitive_task"和"same_topic_long"会直接增加
        # 已经在 triggers 中处理

        self._update_trends()
        return affected

    # ── 自然波动与衰减 ──────────────────────────────────────────────────────

    def decay(self, hours: float = 1.0):
        """
        模拟时间流逝 — 衰减 + 自然向 base_level 靠拢。

        整体效应 = -decay_rate * hours + (base_level - current_level) * drift_factor

        其中 drift_factor 控制自然回归的速度（默认按 10% / 小时向基线靠拢）。
        boredom 具有特殊的 growth_rate（空闲时自增长）。

        Args:
            hours: 模拟小时数（可为小数），默认 1 小时
        """
        for name, h in self._hormones.items():
            current = h["level"]
            base = h["base_level"]
            decay = h["decay_rate"] * hours
            growth = h.get("growth_rate", 0.0) * hours

            # 自然漂移因子 — 每小时向 base_level 靠近 10%
            drift = (base - current) * 0.1 * hours

            # 总变化
            delta = -decay + drift

            # Boredom 特殊处理：空闲时增长
            if name == "boredom":
                # 如果当前高于基线，按正常衰减+漂移；如果低于基线，空闲促使其增长
                # 这里 growth_rate 模拟空闲积累 -> 向更高水平移动
                delta += growth * (1.0 if current < 100 else 0.0)

            h["level"] = self._clamp(current + delta)

        self._update_trends()

    # ── 查询接口 ────────────────────────────────────────────────────────────

    def get_profile(self) -> dict:
        """
        返回所有激素的详细状态。

        Returns:
            {name: {level, display_name, description, trend, dominant, base_level}}
        """
        dominant_name, dominant_strength = self._find_dominant()

        profile = {}
        for name, h in self._hormones.items():
            profile[name] = {
                "level": round(h["level"], 1),
                "display_name": h["display_name"],
                "description": h["description"],
                "trend": h["trend"],
                "base_level": h["base_level"],
                "dominant": name == dominant_name,
                "dominant_strength": round(dominant_strength, 2) if name == dominant_name else 0.0,
            }
        return profile

    def get_dominant(self) -> dict:
        """
        返回当前主导情绪及强度。

        Returns:
            {"name": str, "display_name": str, "strength": float (0~1), "level": float}
        """
        dominant_name, strength = self._find_dominant()
        h = self._hormones[dominant_name]
        return {
            "name": dominant_name,
            "display_name": h["display_name"],
            "description": h["description"],
            "strength": round(strength, 3),
            "level": round(h["level"], 1),
        }

    def get_mood_description(self) -> str:
        """
        返回一段自然语言的情绪描述。

        例如："期待中带着一丝压力"、"满足而放松"、"感到无聊且焦躁"

        Returns:
            情绪描述字符串
        """
        # 按水平排序，取前两名
        sorted_h = sorted(
            self._hormones.items(),
            key=lambda x: x[1]["level"],
            reverse=True,
        )

        top = sorted_h[0][1]
        second = sorted_h[1][1] if len(sorted_h) > 1 else None

        # 形容词映射
        adj_map = {
            "dopamine":  "期待",
            "serotonin": "满足",
            "cortisol":  "压力",
            "oxytocin":  "亲和",
            "boredom":   "无聊",
        }

        # 水平映射到强度副词
        def adverb(level: float) -> str:
            if level >= 80:
                return "非常"
            elif level >= 60:
                return "相当"
            elif level >= 40:
                return "有些"
            else:
                return "略微"

        parts = []

        # 主导情绪
        top_adj = adj_map.get(sorted_h[0][0], sorted_h[0][0])
        top_adv = adverb(top["level"])
        parts.append(f"{top_adv}{top_adj}")

        # 次要情绪（如果有明显影响）
        if second and second["level"] >= 25:
            second_adj = adj_map.get(sorted_h[1][0], sorted_h[1][0])
            second_adv = adverb(second["level"])

            # 连接词
            if top["level"] >= 60 and second["level"] >= 40:
                connector = "且"
            else:
                connector = "，但"

            # 如果是皮质醇（压力），特殊表述
            if sorted_h[1][0] == "cortisol":
                parts.append(f"{connector}带着一丝压力")
            else:
                parts.append(f"{connector}{second_adv}{second_adj}")

        # 如果无聊水平高，补充说明
        boredom_h = self._hormones.get("boredom", {})
        if boredom_h and boredom_h["level"] >= 50 and sorted_h[0][0] != "boredom":
            parts.append("，略感乏味")

        description = "".join(parts)
        return description

    def summarize(self, max_chars: int = 120) -> str:
        """
        返回简短的激素状态摘要，用于系统提示注入。

        Args:
            max_chars: 摘要最大字符数

        Returns:
            例如 "[情绪状态] 多巴胺=45↑ 血清素=38↓ 皮质醇=22→ 催产素=12↑ 无聊=30↑ | 主导: 期待"
        """
        emoji_map = {
            "dopamine":  "✨",
            "serotonin": "😊",
            "cortisol":  "⚡",
            "oxytocin":  "💛",
            "boredom":   "🥱",
        }
        trend_arrow = {"rising": "↑", "falling": "↓", "stable": "→"}

        parts = []
        for name, h in sorted(self._hormones.items()):
            emoji = emoji_map.get(name, "")
            arrow = trend_arrow.get(h["trend"], "→")
            parts.append(f"{emoji}{name}={int(h['level'])}{arrow}")

        dominant = self.get_dominant()
        summary = f"[情绪状态] {' '.join(parts)} | 主导: {dominant['display_name']}({dominant['strength']:.0%})"

        if len(summary) > max_chars:
            # 截断主导部分
            summary = f"[情绪状态] {' '.join(parts)} | 主导: {dominant['display_name']}"

        return summary

    # ── 内部方法 ────────────────────────────────────────────────────────────

    def _clamp(self, value: float) -> float:
        """将值限制在 [0, 100] 范围内。"""
        return max(0.0, min(100.0, value))

    def _update_trends(self):
        """更新每个激素的趋势方向（用于显示上升/下降/稳定）。"""
        # 这里简单地根据当前 level 与 base_level 的关系判断
        # 更精确的实现可以跟踪上次值，但这里使用简化版本
        for name, h in self._hormones.items():
            diff = h["level"] - h["base_level"]
            if abs(diff) < 2.0:
                h["trend"] = "stable"
            elif diff > 0:
                h["trend"] = "rising"
            else:
                h["trend"] = "falling"

    def _find_dominant(self) -> tuple:
        """
        找出当前主导情绪。

        Returns:
            (name, strength) — strength 为 0~1 的归一化强度
        """
        # 对每种激素，计算 "偏离中立" 的程度
        # 多巴胺、血清素、催产素：高 = 积极主导
        # 皮质醇、无聊：高 = 消极主导
        scores = {}
        for name, h in self._hormones.items():
            level = h["level"]
            base = h["base_level"]
            if name in ("cortisol", "boredom"):
                # 消极激素：高水平增加主导权重
                score = (level - base) / (100.0 - base) if base < 100 else 0.0
            else:
                # 积极激素：高水平增加主导权重
                score = (level - base) / (100.0 - base) if base < 100 else 0.0

            # 确保非负
            score = max(0.0, score)
            scores[name] = score

        # 取最高分
        if not scores:
            return ("serotonin", 0.0)

        dominant_name = max(scores, key=scores.get)
        dominant_strength = scores[dominant_name]

        # 如果所有分数都接近0，默认用波动最大的
        if dominant_strength < 0.05:
            # 找水平绝对值最高的
            max_name = max(
                self._hormones.items(),
                key=lambda x: abs(x[1]["level"] - x[1]["base_level"]),
            )[0]
            return (max_name, 0.1)

        return (dominant_name, dominant_strength)

    # ── 便利方法 ────────────────────────────────────────────────────────────

    def get_level(self, name: str) -> float:
        """获取指定激素的当前水平。"""
        return round(self._hormones[name]["level"], 1)

    def reset_all(self):
        """将所有激素重置为 base_level。"""
        for name, h in self._hormones.items():
            h["level"] = h["base_level"]
        self._update_trends()
        self.save()

    def apply_event_batch(self, events: list[dict]):
        """
        批量应用多个事件。

        Args:
            events: [{"event_type": str, "intensity": float}, ...]
        """
        results = []
        for event in events:
            result = self.trigger(
                event_type=event.get("event_type", ""),
                intensity=event.get("intensity", 1.0),
            )
            results.append(result)
        return results

    def __repr__(self) -> str:
        return (
            f"<HormoneSystem "
            f"dopamine={self._hormones['dopamine']['level']:.0f} "
            f"serotonin={self._hormones['serotonin']['level']:.0f} "
            f"cortisol={self._hormones['cortisol']['level']:.0f} "
            f"oxytocin={self._hormones['oxytocin']['level']:.0f} "
            f"boredom={self._hormones['boredom']['level']:.0f}>"
        )


# ── 简单测试 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  HormoneSystem — 情绪化学系统 测试")
    print("=" * 55)

    hs = HormoneSystem()

    print("\n📋 初始状态:")
    profile = hs.get_profile()
    for name, data in profile.items():
        print(f"  {data['display_name']:5s} ({name:10s}) = {data['level']:5.1f}  [{data['trend']}]")

    print(f"\n🎭 主导情绪: {hs.get_dominant()['display_name']} (强度 {hs.get_dominant()['strength']:.0%})")
    print(f"💬 情绪描述: {hs.get_mood_description()}")
    print(f"📝 摘要: {hs.summarize()}")

    print("\n⚡ 触发事件: learning + error + user_praise")
    hs.trigger("learning")       # 多巴胺 +15
    hs.trigger("error")          # 皮质醇 +25
    hs.trigger("user_praise")    # 血清素 +20

    print("\n📋 事件后状态:")
    profile = hs.get_profile()
    for name, data in profile.items():
        print(f"  {data['display_name']:5s} ({name:10s}) = {data['level']:5.1f}  [{data['trend']}]")

    print(f"\n🎭 主导情绪: {hs.get_dominant()['display_name']} (强度 {hs.get_dominant()['strength']:.0%})")
    print(f"💬 情绪描述: {hs.get_mood_description()}")
    print(f"📝 摘要: {hs.summarize()}")

    print("\n⏳ 模拟 2 小时衰减...")
    hs.decay(hours=2.0)

    print("📋 衰减后状态:")
    profile = hs.get_profile()
    for name, data in profile.items():
        print(f"  {data['display_name']:5s} ({name:10s}) = {data['level']:5.1f}  [{data['trend']}]")

    print(f"\n🎭 主导情绪: {hs.get_dominant()['display_name']}")
    print(f"💬 情绪描述: {hs.get_mood_description()}")
    print(f"📝 摘要: {hs.summarize()}")

    print("\n💾 保存到数据库...")
    hs.save()
    print(f"   数据库: {hs.db_path}")

    # 验证持久化
    print("\n🔍 验证持久化...")
    hs2 = HormoneSystem()
    profile2 = hs2.get_profile()
    for name, data in profile2.items():
        orig = profile[name]["level"]
        loaded = data["level"]
        match = "✅" if abs(orig - loaded) < 0.2 else "❌"
        print(f"  {match} {data['display_name']:5s}: {orig:.1f} -> {loaded:.1f}")

    print("\n✅ 测试完成\n")
