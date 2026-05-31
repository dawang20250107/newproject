#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
emotion_memory.py — 情感记忆系统

SQLite 加权存储 + 情绪标签 + 加权检索
数据库文件: /opt/dawang-hermes/mind.db
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")


class EmotionMemory:
    """情感记忆系统，基于 SQLite 的轻量级情感加权存储与检索。"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    # ── 数据库初始化 ────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（每次调用新建，确保线程安全）。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        """创建 emotion_memories 表（如不存在）。"""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS emotion_memories (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    content     TEXT        NOT NULL,
                    valence     REAL        NOT NULL CHECK(valence >= -1.0 AND valence <= 1.0),
                    intensity   REAL        NOT NULL CHECK(intensity >= 0.0 AND intensity <= 1.0),
                    emotions    TEXT        NOT NULL DEFAULT '[]',
                    tags        TEXT        NOT NULL DEFAULT '[]',
                    source      TEXT        DEFAULT '',
                    created_at  TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 索引：加速按情绪权重排序检索
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_emotion_memories_created
                ON emotion_memories(created_at DESC)
            """)
            conn.commit()
        finally:
            conn.close()

    # ── 核心写入 ───────────────────────────────────────────────────

    def store(
        self,
        content: str,
        valence: float,
        intensity: float,
        emotions: list | None = None,
        tags: list | None = None,
        source: str = "",
    ) -> int:
        """
        存入一条情感记忆。

        参数:
            content:   记忆内容文本
            valence:   效价 (-1.0 ~ 1.0)，负值=负面情绪，正值=正面情绪
            intensity: 强度 (0.0 ~ 1.0)
            emotions:  情绪标签列表，如 ['dopamine'] 或 ['cortisol']
            tags:      自定义标签列表
            source:    记忆来源（如 'chat', 'dream', 'journal'）

        返回:
            新记录的自增 ID
        """
        valence = max(-1.0, min(1.0, valence))
        intensity = max(0.0, min(1.0, intensity))
        emotions_json = json.dumps(emotions or [], ensure_ascii=False)
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                INSERT INTO emotion_memories (content, valence, intensity, emotions, tags, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (content, valence, intensity, emotions_json, tags_json, source),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    # ── 加权检索 ───────────────────────────────────────────────────

    def recall(
        self,
        limit: int = 5,
        min_valence: float | None = None,
        max_valence: float | None = None,
        tag: str | None = None,
    ) -> list[dict]:
        """
        按情绪权重检索记忆。

        权重公式: weight = (abs(valence) + intensity) / 2
        按 weight DESC 排序，高 intensity 的记忆优先返回。

        参数:
            limit:       返回条数上限
            min_valence: 最低效价过滤
            max_valence: 最高效价过滤
            tag:         按标签过滤（JSON 数组中包含该 tag）

        返回:
            list[dict]，每条包含 id, content, valence, intensity,
                        emotions, tags, source, created_at, weight
        """
        conditions = []
        params: list = []

        if min_valence is not None:
            conditions.append("valence >= ?")
            params.append(min_valence)
        if max_valence is not None:
            conditions.append("valence <= ?")
            params.append(max_valence)
        if tag is not None:
            # JSON 数组中是否包含指定标签
            conditions.append("tags LIKE ?")
            params.append(f"%\"{tag}\"%")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT
                id,
                content,
                valence,
                intensity,
                emotions,
                tags,
                source,
                created_at,
                (ABS(valence) + intensity) / 2.0 AS weight
            FROM emotion_memories
            WHERE {where_clause}
            ORDER BY weight DESC, created_at DESC
            LIMIT ?
        """
        params.append(limit)

        conn = self._get_conn()
        try:
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "valence": row["valence"],
                    "intensity": row["intensity"],
                    "emotions": json.loads(row["emotions"]),
                    "tags": json.loads(row["tags"]),
                    "source": row["source"],
                    "created_at": row["created_at"],
                    "weight": round(row["weight"], 4),
                })
            return results
        finally:
            conn.close()

    # ── 随机两条（梦境关联） ────────────────────────────────────────

    def random_two(self) -> list[dict]:
        """
        随机取两条记忆（用于梦境关联 / DREAM 场景）。

        返回:
            list[dict]，最多两条（库中不足两条则按实际数量返回）
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, content, valence, intensity, emotions, tags, source, created_at
                FROM emotion_memories
                ORDER BY RANDOM()
                LIMIT 2
                """
            ).fetchall()
            results = []
            for row in rows:
                results.append({
                    "id": row["id"],
                    "content": row["content"],
                    "valence": row["valence"],
                    "intensity": row["intensity"],
                    "emotions": json.loads(row["emotions"]),
                    "tags": json.loads(row["tags"]),
                    "source": row["source"],
                    "created_at": row["created_at"],
                })
            return results
        finally:
            conn.close()

    # ── 心情统计 ───────────────────────────────────────────────────

    def get_mood(self) -> dict:
        """
        返回最近 24 小时的整体心情。

        返回:
            {
                "avg_valence":   float,   # 平均效价
                "avg_intensity": float,   # 平均强度
                "count":         int,     # 24 小时内记忆总数
                "period_hours":  24,
            }
            若 24 小时内无记忆，三者均为 0.0 / 0。
        """
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        conn = self._get_conn()
        try:
            row = conn.execute(
                """
                SELECT
                    COALESCE(AVG(valence), 0.0)   AS avg_valence,
                    COALESCE(AVG(intensity), 0.0) AS avg_intensity,
                    COUNT(*)                       AS cnt
                FROM emotion_memories
                WHERE created_at >= ?
                """,
                (since,),
            ).fetchone()

            return {
                "avg_valence": round(row["avg_valence"], 4),
                "avg_intensity": round(row["avg_intensity"], 4),
                "count": row["cnt"],
                "period_hours": 24,
            }
        finally:
            conn.close()

    # ── 计数 ────────────────────────────────────────────────────────

    def count(self) -> int:
        """返回记忆总数。"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM emotion_memories").fetchone()
            return row["cnt"]
        finally:
            conn.close()


# ── 快速自测 ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    mem = EmotionMemory()

    # 清空测试数据
    conn = mem._get_conn()
    conn.execute("DELETE FROM emotion_memories")
    conn.commit()
    conn.close()

    # 写入示例记忆
    samples = [
        ("今天完成了核心模块，很开心！", 0.85, 0.9, ["dopamine"], ["work", "achievement"], "chat"),
        ("被领导批评了，有点沮丧", -0.6, 0.7, ["cortisol"], ["work", "feedback"], "chat"),
        ("梦见自己在飞翔，自由自在", 0.7, 0.5, ["dopamine", "serotonin"], ["dream"], "dream"),
        ("午后的咖啡和阳光很温暖", 0.5, 0.3, ["serotonin"], ["daily"], "journal"),
        ("deadline 逼近，焦虑不安", -0.8, 0.95, ["cortisol", "adrenaline"], ["work", "stress"], "chat"),
    ]

    print("=== 存储测试数据 ===")
    for s in samples:
        mem.store(*s)
        print(f"  → stored: {s[0][:20]}...")

    print(f"\n=== 总记忆数: {mem.count()} ===")

    print("\n=== 加权检索 (limit=3) ===")
    for r in mem.recall(limit=3):
        print(f"  [{r['weight']:.3f}] {r['content'][:25]:25s}  v={r['valence']:.2f} i={r['intensity']:.2f}")

    print("\n=== 过滤 tag='stress' ===")
    for r in mem.recall(limit=5, tag="stress"):
        print(f"  [{r['weight']:.3f}] {r['content'][:25]:25s}  tags={r['tags']}")

    print("\n=== 随机两条（梦境关联） ===")
    for r in mem.random_two():
        print(f"  - {r['content'][:30]}")

    print("\n=== 24 小时心情 ===")
    mood = mem.get_mood()
    print(f"  平均效价: {mood['avg_valence']:.3f}")
    print(f"  平均强度: {mood['avg_intensity']:.3f}")
    print(f"  记录数量: {mood['count']}")

    print("\n✅ emotion_memory.py 自测完成")
