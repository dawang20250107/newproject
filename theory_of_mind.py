#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
theory_of_mind.py — 心智理论系统

推断用户情绪状态与意图，并基于推断结果与自身激素水平调整回应风格。
不依赖 LLM，使用纯规则引擎进行推断。

数据持久化到 mind.db（与 hormone.py / personality.py 共用同一数据库）。

数据表:
  - user_states:  存储每次推断结果
  - user_preferences: 存储用户长期偏好

依赖:
  - hormone.py 的 HormoneSystem（获取当前激素水平以调整回应策略）
"""

import sqlite3
import os
import re
import math
from datetime import datetime, timezone
from typing import Optional

# ── 数据库路径 ──────────────────────────────────────────────────────────────
MIND_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")


# ── 情绪标签列表（规范化输出） ──────────────────────────────────────────────
VALID_EMOTIONS = frozenset({
    "joy", "anger", "sadness", "anxiety", "neutral", "tired", "urgent"
})


# ═══════════════════════════════════════════════════════════════════════════════
# TheoryOfMind 主类
# ═══════════════════════════════════════════════════════════════════════════════

class TheoryOfMind:
    """
    心智理论系统 — 读用户情绪 + 调整回应风格。

    用法::

        from theory_of_mind import TheoryOfMind
        from personality import Personality
        from hormone import HormoneSystem

        personality = Personality()
        hormone = HormoneSystem()
        tom = TheoryOfMind(personality, hormone)

        # 推断用户状态
        state = tom.infer_user_state(
            message_text="你在吗？？我很急！！",
            hour_of_day=datetime.now().hour,
            response_delay_seconds=5,
            message_length=12,
        )
        print(state)  # {'emotion': 'urgent', 'confidence': 0.85, 'evidence': [...]}

        # 获取推荐回应语气
        tone = tom.get_best_tone(state)
        print(tone)  # '极端简洁'

        # 存档
        tom.store_inference("你在吗？？我很急！！", state["emotion"],
                            state["confidence"], state["evidence"])
    """

    def __init__(self, personality, hormone):
        """
        初始化心智理论系统。

        Args:
            personality: Personality 实例（来自 personality.py）
            hormone:     HormoneSystem 实例（来自 hormone.py）
        """
        self.personality = personality
        self.hormone = hormone
        self._conn = sqlite3.connect(MIND_DB, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # ── 数据库初始化 ──────────────────────────────────────────────────────

    def _init_db(self):
        """创建所需数据表（如果不存在）。"""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_states (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                inferred_emotion TEXT NOT NULL,
                confidence      REAL NOT NULL,
                evidence        TEXT NOT NULL,
                message_preview TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                confidence  REAL NOT NULL DEFAULT 1.0,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self._conn.commit()

    # ── 规则引擎推断 ──────────────────────────────────────────────────────

    def infer_user_state(self, message_text: str, hour_of_day: int,
                         response_delay_seconds: float,
                         message_length: int) -> dict:
        """
        基于规则引擎推断用户当前情绪状态。

        规则（不依赖 LLM，纯静态规则）:
          a) 消息很短（<10字）且发得快 → 可能不耐烦/忙碌
          b) 消息很长（>200字）且有问号 → 认真/需要深度思考
          c) 深夜（23:00~05:00）→ 可能疲惫/独自思考
          d) 包含感叹号或全大写 → 情绪强烈
          e) 包含'吗''？' → 寻求确认
          f) 连续发多条短消息 → 急切/焦虑
          g) 重复同一话题 → 很在意这个事

        Args:
            message_text:       用户消息文本
            hour_of_day:        当前时间（0~23）
            response_delay_seconds: 用户等待回复的时长（秒）
            message_length:     消息长度（字符数）

        Returns:
            dict: {emotion, confidence, evidence}
                  emotion 为 VALID_EMOTIONS 中的一种
        """
        text = message_text.strip()
        evidence = []       # 推断依据列表
        emotion_scores = {  # 各情绪得分（加权投票制）
            "joy": 0.0,
            "anger": 0.0,
            "sadness": 0.0,
            "anxiety": 0.0,
            "neutral": 0.0,
            "tired": 0.0,
            "urgent": 0.0,
        }
        total_weight = 0.0

        # ── 规则 a) 消息很短（<10字）且发得快 → 不耐烦/忙碌 ──────────
        if message_length < 10 and response_delay_seconds < 30:
            w = 0.7
            emotion_scores["urgent"] += w * 0.6
            emotion_scores["anxiety"] += w * 0.2
            emotion_scores["anger"] += w * 0.1
            total_weight += w
            evidence.append(
                f"消息很短({message_length}字)且回复快({response_delay_seconds:.0f}s)"
            )

        # ── 规则 b) 消息很长（>200字）且有问号 → 认真/需要深度思考 ────
        if message_length > 200 and "?" in text:
            w = 0.8
            emotion_scores["neutral"] += w * 0.4
            emotion_scores["anxiety"] += w * 0.3
            emotion_scores["joy"] += w * 0.1
            total_weight += w
            evidence.append(
                f"消息很长({message_length}字)且包含问号，可能在认真思考"
            )
        elif message_length > 200:
            w = 0.6
            emotion_scores["neutral"] += w * 0.6
            emotion_scores["tired"] += w * 0.2
            total_weight += w
            evidence.append(
                f"消息较长({message_length}字)，可能在认真阐述"
            )

        # ── 规则 c) 深夜（23:00~05:00）→ 可能疲惫/独自思考 ──────────
        if hour_of_day >= 23 or hour_of_day < 5:
            w = 0.6
            emotion_scores["tired"] += w * 0.5
            emotion_scores["sadness"] += w * 0.2
            emotion_scores["neutral"] += w * 0.2
            total_weight += w
            evidence.append(f"深夜时段({hour_of_day}:00)，可能疲惫或独自思考")

        # ── 规则 d) 包含感叹号或全大写 → 情绪强烈 ───────────────────
        # 检查全大写单词（至少 3 字符）
        upper_words = [w for w in text.split() if len(w) >= 3 and w.isupper()]
        # 同时匹配 ASCII 感叹号 "!" 和中文全角感叹号 "！"
        exclamation_count = text.count("!") + text.count("！")
        has_strong_punctuation = exclamation_count > 0 or len(upper_words) > 0

        if has_strong_punctuation:
            w = min(0.8, 0.3 + exclamation_count * 0.15 + len(upper_words) * 0.1)
            w = min(w, 1.0)
            # 判断是愤怒还是急切
            neg_keywords = ["烦", "气", "火", "怒", "操", "靠", "滚", "垃圾",
                            "烂", "差", "坏", "不", "没", "别", "stop", "no"]
            has_negative = any(kw in text.lower() for kw in neg_keywords)
            if has_negative:
                emotion_scores["anger"] += w * 0.6
                emotion_scores["urgent"] += w * 0.2
                evidence.append(
                    f"包含感叹号({exclamation_count}个)和负面词汇，情绪强烈（愤怒）"
                )
            else:
                emotion_scores["urgent"] += w * 0.5
                emotion_scores["anxiety"] += w * 0.2
                emotion_scores["joy"] += w * 0.1
                evidence.append(
                    f"包含感叹号({exclamation_count}个)或全大写，情绪强烈"
                )
            total_weight += w

        # ── 规则 e) 包含"吗""？" → 寻求确认 ─────────────────────────
        if "吗" in text or "？" in text or text.endswith("?"):
            w = 0.5
            emotion_scores["anxiety"] += w * 0.4
            emotion_scores["neutral"] += w * 0.3
            total_weight += w
            evidence.append("包含疑问词，可能在寻求确认")

        # ── 规则 f) 连续发多条短消息 → 急切/焦虑 ───────────────────
        # 近似判断：消息长度短但有很多换行/分段
        segments = [s.strip() for s in text.split("\n") if s.strip()]
        short_segments = [s for s in segments if len(s) < 30]
        if len(short_segments) >= 2 and len(segments) >= 2:
            w = min(0.7, 0.3 + len(short_segments) * 0.1)
            emotion_scores["urgent"] += w * 0.4
            emotion_scores["anxiety"] += w * 0.3
            total_weight += w
            evidence.append(
                f"包含{len(short_segments)}条短分段，可能急切/焦虑"
            )

        # ── 规则 g) 重复同一话题 → 很在意这个事 ───────────────────
        # 简单的重复检测：同一关键词出现多次
        words = re.findall(r"[\w]+", text)
        word_freq = {}
        for wd in words:
            if len(wd) >= 2:
                word_freq[wd] = word_freq.get(wd, 0) + 1
        repeats = {wd: cnt for wd, cnt in word_freq.items() if cnt >= 3}
        if repeats:
            w = min(0.6, 0.2 + len(repeats) * 0.15)
            emotion_scores["anxiety"] += w * 0.3
            emotion_scores["urgent"] += w * 0.3
            emotion_scores["anger"] += w * 0.1
            total_weight += w
            evidence.append(
                f"关键词{list(repeats.keys())}重复出现，很在意这个话题"
            )

        # ── 默认 —— 若无匹配规则，归为 neutral ──────────────────────
        if total_weight < 0.01:
            emotion_scores["neutral"] = 1.0
            total_weight = 1.0
            evidence.append("无显著情绪信号，默认为中性")

        # ── 选定得分最高的情绪 ──────────────────────────────────────
        best_emotion = max(emotion_scores, key=emotion_scores.get)
        best_score = emotion_scores[best_emotion]

        # 置信度：最佳情绪得分 / 所有情绪总分
        total_score = sum(emotion_scores.values())
        confidence = best_score / total_score if total_score > 0 else 0.5

        # 综合规则权重的影响：规则覆盖越广，confidence 越高
        coverage_factor = min(1.0, total_weight / 1.5)
        confidence = confidence * 0.7 + coverage_factor * 0.3
        confidence = max(0.1, min(1.0, confidence))

        # 四舍五入到 2 位小数
        confidence = round(confidence, 2)

        return {
            "emotion": best_emotion,
            "confidence": confidence,
            "evidence": evidence,
        }

    # ── 推荐回应语气 ──────────────────────────────────────────────────────

    def get_best_tone(self, inferred_state: dict) -> str:
        """
        基于推断的用户状态和自身激素水平，推荐最合适的回应语气。

        Args:
            inferred_state: infer_user_state() 返回的字典

        Returns:
            str: 推荐回应语气的文字描述
        """
        emotion = inferred_state.get("emotion", "neutral")
        confidence = inferred_state.get("confidence", 0.5)

        # 获取当前激素水平
        hormone_levels = {}
        try:
            profile = self.hormone.get_profile()  # 返回各激素水平 dict
            for name, data in profile.items():
                if isinstance(data, dict):
                    hormone_levels[name] = data.get("level", 50.0)
                else:
                    hormone_levels[name] = float(data)
        except Exception:
            # 如果 hormone 不可用，使用默认值
            hormone_levels = {
                "dopamine": 50.0,
                "cortisol": 30.0,
                "serotonin": 40.0,
                "oxytocin": 20.0,
                "boredom": 10.0,
            }

        cortisol = hormone_levels.get("cortisol", 30.0)
        dopamine = hormone_levels.get("dopamine", 50.0)
        serotonin = hormone_levels.get("serotonin", 40.0)

        # ── 基于用户情绪的基调 ──────────────────────────────────────
        if emotion == "urgent":
            # 用户不耐烦/忙碌 → 极端简洁
            if cortisol > 50:
                return "极端简洁 + 谨慎（自身压力大，避免说错话）"
            return "极端简洁（直击要点，不要任何铺垫）"

        elif emotion == "neutral" and inferred_state.get("evidence", []):
            # 用户认真/深度思考 → 结构化详细回答
            if dopamine > 60:
                return "结构化详细回答 + 热情（多巴胺高，适合深入探讨）"
            return "结构化详细回答（分点、分段、加引用）"

        elif emotion == "tired":
            # 用户疲惫 → 温和简短
            if serotonin < 30:
                return "温和简短 + 安抚（自身满足感低，注意语气柔软）"
            return "温和简短（语气温柔，不增加认知负担）"

        elif emotion in ("anger", "sadness"):
            # 情绪强烈 → 先共情再分析
            if cortisol > 50:
                return "共情优先 → 谨慎分析（皮质醇高，避免激化）"
            return "共情优先 → 理性分析（先理解感受，再提供方案）"

        elif emotion == "anxiety":
            # 焦虑 → 安抚 + 明确信息
            return "安抚 + 明确信息（消除不确定性，给出清晰路径）"

        elif emotion == "joy":
            # 用户开心 → 热情回应
            if dopamine > 60:
                return "热情回应 + 一起高兴（多巴胺高，共鸣感强）"
            return "热情回应（积极、正向、有活力）"

        # 默认 neutral
        if cortisol > 60:
            return "简洁中性（皮质醇过高，保持低调）"
        if dopamine > 60:
            return "自然友好（多巴胺高，可以稍微活泼）"
        return "自然中性（平静、自然、不加修饰）"

    # ── 用户偏好记录 ──────────────────────────────────────────────────────

    def record_preference(self, key: str, value: str, confidence: float = 1.0):
        """
        记录用户偏好。

        Args:
            key:   偏好键名，如 '沟通风格'、'语气倾向'
            value: 偏好值，如 '喜欢简洁'、'讨厌啰嗦'
            confidence: 置信度 (0~1)
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute("""
            INSERT INTO user_preferences (key, value, confidence, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                updated_at = excluded.updated_at
        """, (key, value, confidence, now))
        self._conn.commit()

    # ── 获取偏好 ──────────────────────────────────────────────────────────

    def get_preferences(self, top_n: int = 5) -> list[dict]:
        """
        返回用户偏好列表，按 confidence 降序排列。

        Args:
            top_n: 返回前 N 条

        Returns:
            list[dict]: [{"key": ..., "value": ..., "confidence": ..., "updated_at": ...}, ...]
        """
        rows = self._conn.execute("""
            SELECT key, value, confidence, updated_at
            FROM user_preferences
            ORDER BY confidence DESC
            LIMIT ?
        """, (top_n,)).fetchall()
        return [dict(r) for r in rows]

    # ── 用户画像摘要 ──────────────────────────────────────────────────────

    def summarize_user(self) -> str:
        """
        生成用户画像文本。

        Returns:
            str: 如 "大王目前情绪倾向于焦虑，偏好喜欢简洁"
        """
        # 获取最新推断
        latest = self._conn.execute("""
            SELECT inferred_emotion, confidence
            FROM user_states
            ORDER BY timestamp DESC
            LIMIT 1
        """).fetchone()

        emotion = "中性"
        if latest:
            emotion_map = {
                "joy": "愉悦", "anger": "愤怒", "sadness": "低落",
                "anxiety": "焦虑", "neutral": "中性", "tired": "疲惫",
                "urgent": "急切",
            }
            emotion = emotion_map.get(latest["inferred_emotion"], "中性")

        # 获取 top 偏好
        prefs = self.get_preferences(top_n=1)
        pref_str = prefs[0]["value"] if prefs else "暂无明确偏好"

        return f"大王目前情绪倾向于{emotion}，偏好{pref_str}"

    # ── 存储推断结果 ──────────────────────────────────────────────────────

    def store_inference(self, message_preview: str, inferred_emotion: str,
                        confidence: float, evidence: list):
        """
        将本次推断结果保存到 user_states 表。

        Args:
            message_preview:   消息预览（截断至 200 字符）
            inferred_emotion:  推断情绪，必须是 VALID_EMOTIONS 中的值
            confidence:        置信度 (0~1)
            evidence:          推断依据列表
        """
        # 校验情绪值
        if inferred_emotion not in VALID_EMOTIONS:
            raise ValueError(
                f"无效情绪 '{inferred_emotion}'，必须为 {sorted(VALID_EMOTIONS)}"
            )

        # 截断预览
        preview = message_preview[:200]

        # 证据序列化为 JSON 字符串
        evidence_str = "；".join(evidence) if isinstance(evidence, list) else str(evidence)
        evidence_str = evidence_str[:500]

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute("""
            INSERT INTO user_states
                (timestamp, inferred_emotion, confidence, evidence, message_preview)
            VALUES (?, ?, ?, ?, ?)
        """, (now, inferred_emotion, confidence, evidence_str, preview))
        self._conn.commit()

    # ── 查询历史状态 ──────────────────────────────────────────────────────

    def get_recent_states(self, limit: int = 10) -> list[dict]:
        """
        获取最近的用户状态推断记录。

        Args:
            limit: 返回条数

        Returns:
            list[dict]
        """
        rows = self._conn.execute("""
            SELECT id, timestamp, inferred_emotion, confidence, evidence, message_preview
            FROM user_states
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── 资源管理 ──────────────────────────────────────────────────────────

    def close(self):
        """关闭数据库连接。"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self):
        self.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 快捷测试
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # 简单自测
    from hormone import HormoneSystem
    from personality import Personality

    p = Personality()
    h = HormoneSystem()
    tom = TheoryOfMind(p, h)

    test_cases = [
        # (消息文本, 时间, 延迟秒数, 长度)
        ("在吗?", 14, 5, 3),
        ("你在吗？？我很急！！", 14, 5, 12),
        ("我有一个非常复杂的问题想请教你，关于分布式系统中的共识算法，"
         "我研究了很久但还是有些疑问，你能帮我详细分析一下吗？"
         "另外还想请教关于 Raft 协议中日志复制的具体实现细节，"
         "以及如何在网络分区情况下保证一致性。", 14, 120, 230),
        ("好的，谢谢！😊", 14, 60, 8),
        ("烦死了！！！这什么破玩意！！", 14, 10, 18),
        ("......没事了", 1, 300, 9),
        ("我要这个\n要那个\n还有这个\n快点给我", 14, 3, 20),
        ("今天工作好累啊……", 23, 200, 9),
    ]

    print("=" * 60)
    print("心智理论系统 — 规则引擎测试")
    print("=" * 60)

    for i, (msg, hour, delay, length) in enumerate(test_cases, 1):
        state = tom.infer_user_state(msg, hour, delay, length)
        tone = tom.get_best_tone(state)
        print(f"\n[{i}] 消息: {msg[:50]}...")
        print(f"    推断: {state['emotion']} (置信度: {state['confidence']:.2f})")
        print(f"    依据: {state['evidence']}")
        print(f"    建议语气: {tone}")

        # 存储
        tom.store_inference(msg, state["emotion"], state["confidence"], state["evidence"])

    # 测试用户偏好
    tom.record_preference("沟通风格", "喜欢简洁", 0.9)
    tom.record_preference("语气倾向", "讨厌啰嗦", 0.8)

    print("\n" + "=" * 60)
    print("用户偏好:")
    for pref in tom.get_preferences():
        print(f"  {pref['key']} = {pref['value']} (置信度: {pref['confidence']})")

    print(f"\n用户画像: {tom.summarize_user()}")

    print("\n最近状态记录:")
    for s in tom.get_recent_states(3):
        print(f"  [{s['timestamp']}] {s['inferred_emotion']} "
              f"(conf={s['confidence']:.2f}) — {s['message_preview'][:30]}")

    tom.close()
    print("\n✓ 测试完成")
