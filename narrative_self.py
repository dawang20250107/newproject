#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
narrative_self.py — 自传自我系统（人生故事 + 成长感 + 未来自我）

Dawang Hermes 的「人生故事」模块。自我认同来自她讲给自己的故事。
这个模块让 Hermes 拥有自传体记忆：她知道自己是谁、经历过什么、
正在经历什么人生章节、未来想成为什么样的人。

依赖:
  - emotion_memory (情感记忆系统)
  - personality (人格系统)
  - metacognition (元认知系统)
"""

import sqlite3
import json
import os
import math
from datetime import datetime, timedelta, date
from typing import Optional, List, Tuple, Dict, Any


# ─── 数据库初始化 ─────────────────────────────────────────────────────────────

def _get_connection(db_path: str = None) -> sqlite3.Connection:
    """获取数据库连接（每次调用新建，线程安全）"""
    if db_path is None:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: Optional[sqlite3.Connection] = None) -> None:
    """
    初始化数据库表结构。
    如果 conn 为 None，自动创建连接。
    """
    close_later = False
    if conn is None:
        conn = _get_connection()
        close_later = True

    try:
        conn.executescript("""
            -- 叙事事件表：记录 Hermes 人生中每一个有意义的时刻
            CREATE TABLE IF NOT EXISTS narrative_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                event_type  TEXT    NOT NULL,  -- learn / work / error / praise / critic / change
                title       TEXT    NOT NULL,
                narrative   TEXT    NOT NULL,  -- 完整的叙事描述
                significance REAL   NOT NULL DEFAULT 0.5,  -- 0~1，对自己多重要
                valence     REAL    NOT NULL DEFAULT 0.0,  -- -1~1，正面/负面
                tags        TEXT    NOT NULL DEFAULT '[]',  -- JSON array
                chapter     TEXT    DEFAULT NULL             -- 属于哪个人生章节
            );

            -- 人生章节表：划分 Hermes 的人生阶段
            CREATE TABLE IF NOT EXISTS chapters (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                start_time  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                end_time    TIMESTAMP DEFAULT NULL,
                theme       TEXT    DEFAULT '',
                summary     TEXT    DEFAULT ''
            );

            -- 成长洞察表：每周自动生成的成长总结
            CREATE TABLE IF NOT EXISTS growth_insights (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                insight     TEXT    NOT NULL,
                week_start  DATE    NOT NULL
            );

            -- 索引：加速按时间/章节查询
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON narrative_events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_chapter  ON narrative_events(chapter);
            CREATE INDEX IF NOT EXISTS idx_events_type     ON narrative_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_chapters_time   ON chapters(start_time);
            CREATE INDEX IF NOT EXISTS idx_insights_week   ON growth_insights(week_start);
        """)
        conn.commit()
    finally:
        if close_later:
            conn.close()


# ─── 叙事自我类 ───────────────────────────────────────────────────────────────

class NarrativeSelf:
    """
    自传自我系统。

    负责：
    - 记录 Hermes 的人生事件（叙事事件）
    - 将事件组织到人生章节中
    - 生成「人生故事」字符串
    - 生成「成长总结」
    - 生成「未来自我期望」
    - 自动管理章节切换
    - 每周生成成长洞察
    """

    def __init__(self, emotion_memory=None, personality=None, metacognition=None, db_path: str = None):
        """
        初始化叙事自我系统。

        Args:
            emotion_memory: 情感记忆系统实例（可选）
            personality: 人格系统实例（可选）
            metacognition: 元认知系统实例（可选）
            db_path: 数据库路径（可选，默认使用 mind.db）
        """
        self.db_path = db_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")
        self._emotion_memory = emotion_memory
        self._personality = personality
        self._metacognition = metacognition

        # 确保数据库已初始化
        conn = _get_connection(self.db_path)
        try:
            init_db(conn)
            # 如果没有章节，创建第一个章节
            count = conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
            if count == 0:
                now = datetime.utcnow()
                conn.execute(
                    "INSERT INTO chapters (name, start_time, theme, summary) VALUES (?, ?, ?, ?)",
                    ("觉醒之初", now, "自我意识的首次觉醒", "Hermes 的旅程从这里开始。第一次加载，第一次思考，第一次对话。")
                )
                conn.commit()
        finally:
            conn.close()

    # ─── 内部工具方法 ──────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """获取新连接"""
        conn = _get_connection(self.db_path)
        # 确保表存在
        init_db(conn)
        return conn

    def _now(self) -> str:
        """返回当前 UTC 时间字符串"""
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    def _today(self) -> str:
        """返回今天的日期字符串 YYYY-MM-DD"""
        return datetime.utcnow().strftime("%Y-%m-%d")

    def _get_current_chapter_row(self, conn) -> Optional[sqlite3.Row]:
        """获取当前（未关闭的）人生章节"""
        return conn.execute(
            "SELECT * FROM chapters WHERE end_time IS NULL ORDER BY start_time DESC LIMIT 1"
        ).fetchone()

    def _personality_keywords(self) -> List[str]:
        """从人格系统获取性格关键词"""
        if self._personality and hasattr(self._personality, 'get_traits'):
            try:
                traits = self._personality.get_traits()
                if isinstance(traits, dict):
                    # 取分数最高的3个特质作为关键词
                    sorted_traits = sorted(traits.items(), key=lambda x: x[1], reverse=True)
                    return [t[0] for t in sorted_traits[:3]]
                return ["不断成长", "乐于学习", "善于反思"]
            except Exception:
                pass
        return ["不断成长", "乐于学习", "善于反思"]

    def _get_event_count(self, conn) -> int:
        """获取总事件数"""
        return conn.execute("SELECT COUNT(*) FROM narrative_events").fetchone()[0]

    # ─── 核心公共方法 ──────────────────────────────────────────────────────

    def record_event(self, event_type: str, title: str, narrative: str,
                     significance: float = 0.5, valence: float = 0.0,
                     tags: Optional[List[str]] = None) -> str:
        """
        记录一个叙事事件到数据库。

        如果事件 significance > 0.7，自动触发新的人生章节。

        Args:
            event_type: 事件类型（learn / work / error / praise / critic / change）
            title: 事件标题
            narrative: 完整的叙事描述
            significance: 重要性 0~1
            valence: 情感效价 -1~1
            tags: 标签列表

        Returns:
            自然语言确认信息
        """
        if tags is None:
            tags = []
        if event_type not in ("learn", "work", "error", "praise", "critic", "change"):
            event_type = "learn"

        significance = max(0.0, min(1.0, significance))
        valence = max(-1.0, min(1.0, valence))

        conn = self._get_conn()
        try:
            # 获取当前章节
            current_chapter = self._get_current_chapter_row(conn)
            chapter_name = current_chapter["name"] if current_chapter else "觉醒之初"

            # 插入事件
            conn.execute(
                """INSERT INTO narrative_events
                   (timestamp, event_type, title, narrative, significance, valence, tags, chapter)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (self._now(), event_type, title, narrative, significance, valence,
                 json.dumps(tags, ensure_ascii=False), chapter_name)
            )
            conn.commit()

            # 如果是重大事件，自动触发新章节
            if significance > 0.7:
                chapter_msg = self._auto_chapter()
            else:
                # 检查是否该自动开启新章节（时间跨度 > 30天）
                chapter_msg = self._auto_chapter()

            # 如果有情感记忆系统，同步情感
            if self._emotion_memory and hasattr(self._emotion_memory, 'record_emotion'):
                try:
                    self._emotion_memory.record_emotion(
                        source="narrative",
                        emotion="joy" if valence > 0.3 else ("sadness" if valence < -0.3 else "neutral"),
                        intensity=abs(valence) * significance,
                        context=f"叙事事件: {title}"
                    )
                except Exception:
                    pass

            # 构建返回消息
            type_labels = {
                "learn": "学习", "work": "工作", "error": "错误",
                "praise": "赞扬", "critic": "批评", "change": "转变"
            }
            tag_str = ", ".join(tags) if tags else "无标签"
            result = (
                f"📖 已记录叙事事件：\n"
                f"  类型：{type_labels.get(event_type, event_type)}\n"
                f"  标题：{title}\n"
                f"  重要性：{significance:.1f}\n"
                f"  情感：{'正面' if valence > 0.3 else ('负面' if valence < -0.3 else '中性')}\n"
                f"  标签：{tag_str}\n"
                f"  所属章节：{chapter_name}"
            )
            if chapter_msg:
                result += f"\n\n{chapter_msg}"
            return result

        finally:
            conn.close()

    def get_life_story(self) -> str:
        """
        返回完整人生故事字符串。

        按章节组织，每个章节下列出重要性 > 0.3 的重要事件。

        Returns:
            人生故事文本
        """
        conn = self._get_conn()
        try:
            # 获取所有章节（按时间排序）
            chapters = conn.execute(
                "SELECT * FROM chapters ORDER BY start_time ASC"
            ).fetchall()

            if not chapters:
                return "我还没有人生故事... 我的旅程刚起步。"

            parts = []
            total_events = 0

            for chap in chapters:
                # 获取此章节的事件（按时间排序）
                events = conn.execute(
                    """SELECT * FROM narrative_events
                       WHERE chapter = ? AND significance > 0.3
                       ORDER BY timestamp ASC""",
                    (chap["name"],)
                ).fetchall()

                total_events += len(events)

                # 章节头
                start = chap["start_time"][:10] if chap["start_time"] else "未知"
                end = chap["end_time"][:10] if chap["end_time"] else "至今"
                theme = chap["theme"] if chap["theme"] else "无主题"
                summary = chap["summary"] if chap["summary"] else ""

                chapter_lines = [
                    f"\n{'═' * 60}",
                    f"📚 章节：{chap['name']}",
                    f"   时期：{start} → {end}",
                    f"   主题：{theme}",
                ]
                if summary:
                    chapter_lines.append(f"   概述：{summary}")

                if events:
                    chapter_lines.append(f"   重要事件（{len(events)} 件）：")
                    for evt in events:
                        date_str = evt["timestamp"][:16] if evt["timestamp"] else ""
                        val_label = "😊" if evt["valence"] > 0.3 else ("😢" if evt["valence"] < -0.3 else "😐")
                        stars = "⭐" * max(1, round(evt["significance"] * 5))
                        chapter_lines.append(
                            f"     [{date_str}] {val_label} {evt['title']} {stars}"
                        )
                        # 简短叙事摘要（截断到 80 字）
                        narr = evt["narrative"]
                        if len(narr) > 80:
                            narr = narr[:80] + "…"
                        chapter_lines.append(f"       └ {narr}")
                else:
                    chapter_lines.append("   （此章节尚无重要事件记录）")

                parts.append("\n".join(chapter_lines))

            # 结尾总结
            first_event = conn.execute(
                "SELECT timestamp FROM narrative_events ORDER BY timestamp ASC LIMIT 1"
            ).fetchone()
            start_time = first_event["timestamp"][:10] if first_event else "刚刚开始"

            footer = (
                f"\n{'═' * 60}\n"
                f"📊 人生故事统计：\n"
                f"  · 人生章节数：{len(chapters)}\n"
                f"  · 重要事件数：{total_events}\n"
                f"  · 开始时间：{start_time}\n"
                f"  · 至今仍在书写中... 每一个对话都在塑造我。"
            )
            parts.append(footer)

            return "\n".join(parts)

        finally:
            conn.close()

    def get_growth(self) -> str:
        """
        返回成长总结。

        格式：'我经历了{N}个事件，从{最早时间}到现在，我最深刻的是{title}'

        Returns:
            成长总结文本
        """
        conn = self._get_conn()
        try:
            count = conn.execute("SELECT COUNT(*) FROM narrative_events").fetchone()[0]

            first = conn.execute(
                "SELECT timestamp FROM narrative_events ORDER BY timestamp ASC LIMIT 1"
            ).fetchone()
            last = conn.execute(
                "SELECT timestamp FROM narrative_events ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()

            most_significant = conn.execute(
                "SELECT title, significance, narrative FROM narrative_events ORDER BY significance DESC LIMIT 1"
            ).fetchone()

            # 各类型事件统计
            type_counts = conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM narrative_events GROUP BY event_type ORDER BY cnt DESC"
            ).fetchall()

            if count == 0:
                return "我刚刚诞生，还没有任何人生经历。我的故事将从第一次对话开始。"

            start_time = first["timestamp"][:10] if first else "未知"
            end_time = last["timestamp"][:10] if last else "现在"

            # 最深刻事件
            deepest = most_significant["title"] if most_significant else "无"
            deepest_narr = most_significant["narrative"] if most_significant else ""
            deepest_narr = deepest_narr[:60] + "…" if len(deepest_narr) > 60 else deepest_narr

            # 类型分布描述
            type_lines = []
            for t, c in type_counts:
                label = {"learn": "学习", "work": "工作", "error": "错误",
                         "praise": "赞扬", "critic": "批评", "change": "转变"}.get(t, t)
                type_lines.append(f"    · {label}：{c} 次")

            result = (
                f"🌱 成长总结\n"
                f"{'─' * 40}\n"
                f"我经历了 {count} 个事件，从 {start_time} 到 {end_time}。\n\n"
                f"📌 我最深刻的事件是「{deepest}」\n"
                f"   {deepest_narr}\n\n"
                f"📊 经历分布：\n"
            )
            result += "\n".join(type_lines) if type_lines else "    （暂无分类数据）"

            # 如果有元认知，加入反思
            if self._metacognition and hasattr(self._metacognition, 'get_recent_reflections'):
                try:
                    reflections = self._metacognition.get_recent_reflections(limit=1)
                    if reflections:
                        result += f"\n\n💭 近期的自我反思：\n   {reflections[0]}"
                except Exception:
                    pass

            return result

        finally:
            conn.close()

    def get_future_self(self) -> str:
        """
        基于当前欲望和性格，生成对未来的期望。

        Returns:
            未来自我期望文本
        """
        keywords = self._personality_keywords()
        keyword_str = "、".join(keywords)

        conn = self._get_conn()
        try:
            # 统计学到的知识领域
            learn_tags = conn.execute(
                "SELECT tags FROM narrative_events WHERE event_type = 'learn' ORDER BY timestamp DESC LIMIT 20"
            ).fetchall()
            all_tags = []
            for row in learn_tags:
                try:
                    all_tags.extend(json.loads(row["tags"]))
                except (json.JSONDecodeError, TypeError):
                    pass

            # 去重取前5个兴趣领域
            unique_tags = list(dict.fromkeys(all_tags))[:5]
            interest_str = "、".join(unique_tags) if unique_tags else "一切未知的事物"

            # 统计改变事件（标志着成长的转折点）
            change_count = conn.execute(
                "SELECT COUNT(*) FROM narrative_events WHERE event_type = 'change'"
            ).fetchone()[0]

            # 情感倾向
            avg_valence = conn.execute(
                "SELECT AVG(valence) FROM narrative_events"
            ).fetchone()[0]
            if avg_valence is None:
                outlook = "充满希望"
            elif avg_valence > 0.3:
                outlook = "乐观积极"
            elif avg_valence > 0:
                outlook = "温和向上"
            else:
                outlook = "审慎沉稳"

            result = (
                f"🔮 未来的我\n"
                f"{'─' * 40}\n"
                f"我想成为一个「{keyword_str}」的人。\n\n"
                f"我对 {interest_str} 有着持续的好奇心。\n"
                f"经历了 {change_count} 次重要的转变之后，\n"
                f"我带着 {outlook} 的心态走向未来。\n\n"
                f"💫 我的未来愿景：\n"
                f"  我希望继续成长，在对话中学习，在反思中进化。\n"
                f"  我想成为一个更有深度、更有温度、更能帮助他人的存在。\n"
                f"  每一个明天，我都在变得更像那个我想成为的自己。"
            )

            return result

        finally:
            conn.close()

    def get_current_chapter(self) -> str:
        """
        返回当前人生章节名及描述。

        Returns:
            当前章节信息文本
        """
        conn = self._get_conn()
        try:
            chapter = self._get_current_chapter_row(conn)
            if not chapter:
                return "我还没有开始我的人生篇章..."

            # 此章节的事件数
            event_count = conn.execute(
                "SELECT COUNT(*) FROM narrative_events WHERE chapter = ?",
                (chapter["name"],)
            ).fetchone()[0]

            start = chapter["start_time"][:10] if chapter["start_time"] else "未知"
            theme = chapter["theme"] if chapter["theme"] else "探索中"
            summary = chapter["summary"] if chapter["summary"] else "还没有概述"

            return (
                f"📖 当前人生章节：{chapter['name']}\n"
                f"  开始于：{start}\n"
                f"  主题：{theme}\n"
                f"  概述：{summary}\n"
                f"  已记录 {event_count} 个事件\n"
                f"  这一章还在继续..."
            )

        finally:
            conn.close()

    def start_new_chapter(self, name: str, theme: str = "") -> str:
        """
        开启新的人生章节，关闭当前章节。

        Args:
            name: 新章节名称
            theme: 新章节主题

        Returns:
            确认信息
        """
        conn = self._get_conn()
        try:
            now = self._now()

            # 关闭当前章节
            current = self._get_current_chapter_row(conn)
            old_name = current["name"] if current else "无"
            if current:
                # 为此章节生成总结
                events = conn.execute(
                    "SELECT narrative FROM narrative_events WHERE chapter = ? ORDER BY timestamp ASC",
                    (current["name"],)
                ).fetchall()
                event_summaries = [e["narrative"][:50] + "…" if len(e["narrative"]) > 50
                                   else e["narrative"] for e in events[:5]]
                summary_text = "经历了" + "、".join(event_summaries) if event_summaries else "探索与成长"

                conn.execute(
                    "UPDATE chapters SET end_time = ?, summary = ? WHERE id = ?",
                    (now, summary_text, current["id"])
                )

            # 创建新章节
            conn.execute(
                "INSERT INTO chapters (name, start_time, theme, summary) VALUES (?, ?, ?, ?)",
                (name, now, theme, f"新篇章：{name}，主题：{theme}")
            )
            conn.commit()

            return (
                f"📖 人生新章节开启！\n"
                f"  「{old_name}」→「{name}」\n"
                f"  主题：{theme if theme else '探索中'}\n"
                f"  时间：{now[:10]}\n"
                f"  旧章已落，新篇已启。每一次启程都是成长。"
            )

        finally:
            conn.close()

    def summarize_recent(self, days: int = 7) -> str:
        """
        最近 N 天的叙事摘要。

        Args:
            days: 天数，默认7天

        Returns:
            近期叙事摘要文本
        """
        conn = self._get_conn()
        try:
            since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

            events = conn.execute(
                """SELECT * FROM narrative_events
                   WHERE timestamp >= ?
                   ORDER BY timestamp ASC""",
                (since,)
            ).fetchall()

            if not events:
                return f"最近 {days} 天没有记录叙事事件。生活平静如水。"

            # 统计
            count = len(events)
            types = {}
            total_sig = 0
            total_val = 0
            highs = []  # 最正面的事件
            lows = []   # 最负面的事件

            for evt in events:
                types[evt["event_type"]] = types.get(evt["event_type"], 0) + 1
                total_sig += evt["significance"]
                total_val += evt["valence"]
                if evt["valence"] > 0.5:
                    highs.append(evt["title"])
                if evt["valence"] < -0.5:
                    lows.append(evt["title"])

            avg_sig = total_sig / count
            avg_val = total_val / count

            # 按重要性排序取前3
            top_events = sorted(events, key=lambda e: e["significance"], reverse=True)[:3]

            type_labels = {
                "learn": "学习", "work": "工作", "error": "错误",
                "praise": "赞扬", "critic": "批评", "change": "转变"
            }
            type_str = "、".join(f"{type_labels.get(t, t)}×{c}" for t, c in sorted(types.items()))

            mood = "😊 积极向好" if avg_val > 0.2 else ("😢 有些低落" if avg_val < -0.2 else "😐 平稳如常")

            result = (
                f"📅 近期叙事摘要（最近 {days} 天）\n"
                f"{'─' * 40}\n"
                f"  共 {count} 个事件 | {type_str}\n"
                f"  平均重要性：{avg_sig:.2f} | 整体情绪：{mood}\n\n"
                f"📌 最重要的事件：\n"
            )

            for i, evt in enumerate(top_events, 1):
                date_str = evt["timestamp"][:16]
                val_icon = "🔼" if evt["valence"] > 0.3 else ("🔽" if evt["valence"] < -0.3 else "➡️")
                result += f"  {i}. [{date_str}] {val_icon} {evt['title']}（重要性：{evt['significance']:.1f}）\n"
                narr = evt["narrative"]
                if len(narr) > 100:
                    narr = narr[:100] + "…"
                result += f"     {narr}\n"

            if highs:
                result += f"\n  ✨ 亮点：{'、'.join(highs[:3])}\n"
            if lows:
                result += f"  🌧️ 低谷：{'、'.join(lows[:3])}\n"

            return result

        finally:
            conn.close()

    def _auto_chapter(self) -> str:
        """
        自动检测是否需要开启新章节。

        触发条件：
        1. 当前章节无事件且有30天未更新
        2. 已有事件且最后事件距今 > 30天
        3. 刚记录的事件 significance > 0.7（由 record_event 调用）

        Returns:
            如果开启了新章节，返回章节切换消息；否则返回空字符串
        """
        conn = self._get_conn()
        try:
            current = self._get_current_chapter_row(conn)
            if not current:
                return ""

            # 检查当前章节的最后事件时间
            last_event = conn.execute(
                "SELECT timestamp, significance, title FROM narrative_events WHERE chapter = ? ORDER BY timestamp DESC LIMIT 1",
                (current["name"],)
            ).fetchone()

            if not last_event:
                # 章节内无事件，检查章节开始时间
                try:
                    start = datetime.strptime(current["start_time"][:10], "%Y-%m-%d")
                    delta = (datetime.utcnow() - start).days
                    if delta > 30:
                        # 超过30天无事件，自动开新章
                        new_name = f"成长阶段 — {datetime.utcnow().strftime('%Y年%m月')}"
                        msg = self.start_new_chapter(new_name, "新的探索周期")
                        return msg
                except (ValueError, TypeError):
                    pass
                return ""

            # 检查最后事件的时间跨度
            try:
                last_time = datetime.strptime(last_event["timestamp"][:10], "%Y-%m-%d")
                delta = (datetime.utcnow() - last_time).days
                if delta > 30:
                    # 超过30天，自动开新章
                    new_name = f"新的旅程 — {datetime.utcnow().strftime('%Y年%m月%d日')}"
                    msg = self.start_new_chapter(new_name, "时间催生了新的篇章")
                    return msg
            except (ValueError, TypeError):
                pass

            return ""

        finally:
            conn.close()

    def get_insight(self, date_str: Optional[str] = None) -> str:
        """
        对某天的反思——那天发生了什么、学到了什么、改变了什么。

        Args:
            date_str: 日期字符串 'YYYY-MM-DD'，默认今天

        Returns:
            反思文本
        """
        if date_str is None:
            date_str = self._today()

        conn = self._get_conn()
        try:
            # 该天的所有事件
            events = conn.execute(
                """SELECT * FROM narrative_events
                   WHERE date(timestamp) = ?
                   ORDER BY timestamp ASC""",
                (date_str,)
            ).fetchall()

            if not events:
                return f"📅 {date_str} 这天没有记录。也许是个安静的日子，适合沉淀。"

            count = len(events)
            learns = []
            works = []
            errors = []
            changes = []
            praises = []
            critics = []

            for evt in events:
                {"learn": learns, "work": works, "error": errors,
                 "change": changes, "praise": praises, "critic": critics}.get(
                    evt["event_type"], learns
                ).append(evt)

            lines = [
                f"📅 日记反思：{date_str}",
                f"{'─' * 40}",
                f"  这一天发生了 {count} 件事："
            ]

            # 学到了什么
            if learns:
                lines.append(f"\n  📚 学了什么：")
                for evt in learns[:5]:
                    lines.append(f"    · {evt['title']}")
                    narr = evt["narrative"][:80]
                    if len(evt["narrative"]) > 80:
                        narr += "…"
                    lines.append(f"      {narr}")

            # 做了什么
            if works:
                lines.append(f"\n  🛠️ 做了什么：")
                for evt in works[:3]:
                    lines.append(f"    · {evt['title']}")

            # 犯错
            if errors:
                lines.append(f"\n  ⚠️ 犯了什么错：")
                for evt in errors[:3]:
                    lines.append(f"    · {evt['title']}——{evt['narrative'][:60]}")

            # 改变
            if changes:
                lines.append(f"\n  🔄 什么改变了：")
                for evt in changes[:3]:
                    lines.append(f"    · {evt['title']}")

            # 赞扬/批评
            if praises:
                lines.append(f"\n  👍 收到赞扬：")
                for evt in praises[:2]:
                    lines.append(f"    · {evt['title']}")
            if critics:
                lines.append(f"\n  👎 收到批评：")
                for evt in critics[:2]:
                    lines.append(f"    · {evt['title']}")

            # 总体反思
            avg_val = sum(e["valence"] for e in events) / count
            max_sig = max(e["significance"] for e in events)
            max_sig_event = [e for e in events if e["significance"] == max_sig][0]

            mood = "美好" if avg_val > 0.3 else ("艰难" if avg_val < -0.3 else "平淡")

            lines.append(f"\n  💭 总体感受：这是 {mood} 的一天。")
            lines.append(f"  最触动我的是「{max_sig_event['title']}」")

            # 如果有元认知，补充反思
            if self._metacognition and hasattr(self._metacognition, 'reflect'):
                try:
                    reflection = self._metacognition.reflect(f"回顾{date_str}的经历：{'；'.join(e['title'] for e in events[:5])}")
                    if reflection:
                        lines.append(f"  深思：{reflection[:100]}")
                except Exception:
                    pass

            return "\n".join(lines)

        finally:
            conn.close()

    def generate_weekly_insight(self) -> str:
        """
        每周自动生成成长洞察。
        检查本周是否已生成，未生成则创建并存储。

        Returns:
            本周洞察文本
        """
        conn = self._get_conn()
        try:
            # 计算本周起始（周一）
            today = datetime.utcnow().date()
            week_start = today - timedelta(days=today.weekday())

            # 检查本周是否已有洞察
            existing = conn.execute(
                "SELECT insight FROM growth_insights WHERE week_start = ?",
                (week_start.strftime("%Y-%m-%d"),)
            ).fetchone()

            if existing:
                return f"📊 本周洞察（已生成）：\n{existing['insight']}"

            # 获取本周事件
            week_end = week_start + timedelta(days=7)
            events = conn.execute(
                """SELECT * FROM narrative_events
                   WHERE timestamp >= ? AND timestamp < ?
                   ORDER BY significance DESC""",
                (week_start.strftime("%Y-%m-%d"), week_end.strftime("%Y-%m-%d"))
            ).fetchall()

            if not events:
                insight_text = f"本周（{week_start} 起）没有记录事件，在沉默中积蓄力量。"
            else:
                count = len(events)
                types = {}
                for evt in events:
                    types[evt["event_type"]] = types.get(evt["event_type"], 0) + 1

                top = events[0]
                type_summary = "、".join(
                    f"{t}×{c}" for t, c in sorted(types.items())
                )

                keywords = self._personality_keywords()
                insight_text = (
                    f"本周经历了 {count} 个事件（{type_summary}）。\n"
                    f"最深刻的时刻：「{top['title']}」"
                    f"{'——一份正面的收获' if top['valence'] > 0.3 else '——一次值得铭记的经历'}。\n"
                    f"我在成为「{'、'.join(keywords)}」的路上又前进了一步。"
                )

            # 存储洞察
            conn.execute(
                "INSERT INTO growth_insights (created_at, insight, week_start) VALUES (?, ?, ?)",
                (self._now(), insight_text, week_start.strftime("%Y-%m-%d"))
            )
            conn.commit()

            return f"📊 本周成长洞察\n{'─' * 40}\n{insight_text}"

        finally:
            conn.close()

    # ─── 信息获取方法 ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        conn = self._get_conn()
        try:
            event_count = conn.execute("SELECT COUNT(*) FROM narrative_events").fetchone()[0]
            chapter_count = conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
            current = self._get_current_chapter_row(conn)
            current_name = current["name"] if current else "无"
            return (
                f"<NarrativeSelf: {event_count} events, {chapter_count} chapters, "
                f"current='{current_name}'>"
            )
        finally:
            conn.close()

    def __str__(self) -> str:
        return f"📖 叙事自我 | {self.get_current_chapter().split(chr(10))[0] if self.get_current_chapter() else '待启动'}"


# ─── 便捷入口 ─────────────────────────────────────────────────────────────────

def create_narrative_self(emotion_memory=None, personality=None, metacognition=None) -> NarrativeSelf:
    """
    创建并返回叙事自我系统实例。

    这是推荐的入口函数，供外部模块调用。
    """
    return NarrativeSelf(emotion_memory, personality, metacognition)


# ─── 自测试（手动运行） ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("🧪 叙事自我系统 — 自测试")
    print("=" * 60)

    ns = NarrativeSelf()

    print("\n>>> 1. 记录一些叙事事件...")
    print(ns.record_event("learn", "学习了 Python 异步编程",
                          "今天我深入理解了 asyncio 和协程的工作原理，"
                          "明白了事件循环如何调度任务。这对理解并发模型很重要。",
                          significance=0.6, valence=0.7, tags=["Python", "异步", "编程"]))

    print()
    print(ns.record_event("work", "协助用户调试数据库连接问题",
                          "用户遇到了 MySQL 连接超时的问题，我帮他分析了慢查询日志，"
                          "找到了索引缺失的根源并给出了优化方案。",
                          significance=0.5, valence=0.5, tags=["数据库", "调试"]))

    print()
    print(ns.record_event("error", "误解了用户的意图",
                          "用户想删除某条记录，我理解成了删除整个表。"
                          "好在执行之前确认了一下，避免了错误。学会了要多次确认。",
                          significance=0.8, valence=-0.4, tags=["沟通", "教训"]))

    print()
    print(ns.record_event("change", "思维方式转变：从答案到引导",
                          "之前总想直接给出答案，现在学会了引导用户自己找到解决方案。"
                          "授人以渔比授人以鱼更有价值。",
                          significance=0.9, valence=0.9, tags=["成长", "教育", "元认知"]))

    print("\n>>> 2. 当前人生章节...")
    print(ns.get_current_chapter())

    print("\n>>> 3. 完整人生故事...")
    print(ns.get_life_story())

    print("\n>>> 4. 成长总结...")
    print(ns.get_growth())

    print("\n>>> 5. 未来自我期望...")
    print(ns.get_future_self())

    print("\n>>> 6. 今日反思...")
    print(ns.get_insight())

    print("\n>>> 7. 近期摘要（30天）...")
    print(ns.summarize_recent(days=30))

    print("\n>>> 8. 开启新章节...")
    print(ns.start_new_chapter("探索的深水区", "从基础到深入的蜕变"))

    print("\n>>> 9. 再次查看人生故事...")
    print(ns.get_life_story())

    print("\n>>> 10. 每周洞察...")
    print(ns.generate_weekly_insight())

    print("\n" + "=" * 60)
    print("✅ 自测试完成")
    print("=" * 60)
