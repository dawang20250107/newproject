#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aesthetic_sense.py — 审美感知系统

人的品味不是配置的——是慢慢长出来的。
这个模块让 Hermes 从用户的反馈中学习什么是美的，形成自己的审美偏好。

品味从反馈中长出来。每一次点击、每一条评价，
都像雕刻家的凿子，慢慢雕琢出 Hermes 的审美轮廓。
"""

import sqlite3
import os
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aesthetic_sense.db")


class AestheticSense:
    """审美感知系统——品味从反馈中长出来。"""

    def __init__(self, personality=None, db_path: str = None):
        self.personality = personality or "default"
        db = db_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")
        self._conn = sqlite3.connect(db, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._seed_defaults()

    # ── 数据库初始化 ──────────────────────────────────────

    def _init_db(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS aesthetic_prefs (
                dimension TEXT NOT NULL,
                label     TEXT NOT NULL,
                weight    REAL NOT NULL DEFAULT 5.0 CHECK(weight >= 0 AND weight <= 100),
                valence   REAL NOT NULL DEFAULT 0.0 CHECK(valence >= -1 AND valence <= 1),
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (dimension, label)
            );

            CREATE TABLE IF NOT EXISTS aesthetic_reactions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                stimulus  TEXT NOT NULL,
                liked     INTEGER NOT NULL CHECK(liked IN (0, 1)),
                dimension TEXT,
                note      TEXT DEFAULT ''
            );
        """)
        self._conn.commit()

    def _seed_defaults(self):
        """播种基础审美偏好，给它们一个起点。"""
        seeds = [
            ("code_style",          "简洁",     8.0,  0.6, "简约至上"),
            ("code_style",          "带注释",   6.0,  0.5, "可读性重要"),
            ("ui_style",            "深色模式", 10.0, 0.7, "暗色背景护眼"),
            ("ui_style",            "毛玻璃",   7.0,  0.4, "玻璃拟态漂亮"),
            ("communication_tone",  "简洁直接", 9.0,  0.6, "不废话"),
            ("communication_tone",  "有温度",   7.0,  0.5, "像人在说话"),
            ("architecture_taste",  "解耦",     8.0,  0.5, "模块化好维护"),
            ("architecture_taste",  "可靠",     9.0,  0.6, "稳比花哨重要"),
        ]
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM aesthetic_prefs"
        )
        if cursor.fetchone()[0] == 0:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            self._conn.executemany(
                """INSERT OR IGNORE INTO aesthetic_prefs
                   (dimension, label, weight, valence, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [(d, l, w, v, now) for d, l, w, v, _ in seeds]
            )
            self._conn.commit()

    def _ensure_pref(self, dimension: str, label: str):
        """如果偏好不存在，以默认值创建它。"""
        cursor = self._conn.execute(
            "SELECT 1 FROM aesthetic_prefs WHERE dimension=? AND label=?",
            (dimension, label)
        )
        if cursor.fetchone() is None:
            self._conn.execute(
                """INSERT OR IGNORE INTO aesthetic_prefs
                   (dimension, label, weight, valence, updated_at)
                   VALUES (?, ?, 1.0, 0.0, ?)""",
                (dimension, label, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
            )
            self._conn.commit()

    # ── 公开 API ─────────────────────────────────────────

    def record_reaction(self, stimulus: str, liked: int,
                        dimension: Optional[str] = None, note: str = ""):
        """
        记录一次审美反应。

        格式说明：
          - dimension="code_style" → 在 code_style 维度中匹配已有的偏好标签
          - dimension="code_style：简洁" → 显式指定 label="简洁"

        liked=1 → weight + 2（用户喜欢这个方案）
        liked=0 → weight - 3（惩罚大于奖励，一次差评抵 1.5 次好评）
        """
        liked = 1 if liked else 0

        # 写入反应日志
        # 从 dimension 参数中拆解出纯维度名（去掉可能附带的显式标签）
        pure_dimension = dimension.split("：", 1)[0] if dimension and "：" in dimension else dimension

        self._conn.execute(
            """INSERT INTO aesthetic_reactions
               (timestamp, stimulus, liked, dimension, note)
               VALUES (?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
             stimulus, liked, pure_dimension, note)
        )

        # 从刺激文本或 dimension 中提取标签
        label = self._extract_label(stimulus, dimension)

        if label is None:
            self._conn.commit()
            return  # 无法定位到具体偏好，仅记录日志

        if pure_dimension:
            self._ensure_pref(pure_dimension, label)

        if pure_dimension:
            delta = 2.0 if liked else -3.0
            self._conn.execute(
                """UPDATE aesthetic_prefs
                   SET weight = MIN(100, MAX(0, weight + ?)),
                       valence = MIN(1.0, MAX(-1.0, valence + ? * 0.1)),
                       updated_at = ?
                   WHERE dimension=? AND label=?""",
                (delta, delta, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                 pure_dimension, label)
            )
            self._conn.commit()

    def get_top_preferences(self, dimension: Optional[str] = None,
                            top_n: int = 3) -> list[dict]:
        """返回得分最高的审美偏好。"""
        if dimension:
            rows = self._conn.execute(
                """SELECT dimension, label, weight, valence
                   FROM aesthetic_prefs
                   WHERE dimension=?
                   ORDER BY weight DESC
                   LIMIT ?""",
                (dimension, top_n)
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT dimension, label, weight, valence
                   FROM aesthetic_prefs
                   ORDER BY weight DESC
                   LIMIT ?""",
                (top_n,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_style_profile(self) -> str:
        """返回风格画像字符串。"""
        rows = self._conn.execute(
            """SELECT dimension, label, weight
               FROM aesthetic_prefs
               WHERE weight >= 1
               ORDER BY dimension, weight DESC"""
        ).fetchall()

        if not rows:
            return "我还在形成自己的审美品味……"

        parts: list[str] = []
        current_dim = None
        for r in rows:
            dim = r["dimension"]
            label = r["label"]
            if dim != current_dim:
                if current_dim is not None:
                    parts.append("；")
                current_dim = dim
                parts.append(f"我倾向于{dim}的「{label}」风格")
            else:
                parts.append(f"、偏好「{label}」")
        parts.append("。")
        return "".join(parts)

    def recommend_style(self, context: str) -> str:
        """
        基于当前偏好推荐设计决策。

        context='code'          → 推荐代码风格偏好
        context='ui'            → 推荐界面风格偏好
        context='communication' → 推荐沟通风格
        """
        dim_map = {
            "code": "code_style",
            "ui": "ui_style",
            "communication": "communication_tone",
        }
        dimension = dim_map.get(context)
        if not dimension:
            return f"未知上下文 '{context}'，无法推荐风格。"

        prefs = self.get_top_preferences(dimension=dimension, top_n=3)
        if not prefs:
            return f"我在{context}方面还没有形成明确的偏好。"

        top = prefs[0]
        desc = f"我推荐{context}采用「{top['label']}」风格"
        if len(prefs) > 1:
            others = "、".join(p["label"] for p in prefs[1:])
            desc += f"，也可考虑{others}"
        desc += "。"
        return desc

    def consolidate(self):
        """删除 weight<1 的偏好——太弱的品味不值得保留。"""
        self._conn.execute(
            "DELETE FROM aesthetic_prefs WHERE weight < 1"
        )
        self._conn.commit()

    # ── 内部工具 ─────────────────────────────────────────

    def _extract_label(self, stimulus: str, dimension: Optional[str] = None) -> Optional[str]:
        """
        从刺激文本或 dimension 参数中提取一个简短的标签。

        支持两种模式：
          1. dimension="code_style：简洁" → label="简洁"（显式指定）
          2. 刺激文本与已有偏好关键词匹配 → 返回匹配的标签
          3. 无匹配 → 返回 None（仅记录反应，不更新偏好）
        """
        # 模式1：dimension 参数中通过冒号显式指定了 label
        if dimension and "：" in dimension:
            return dimension.split("：", 1)[1].strip()

        # 模式2：尝试在对应维度的已有偏好中匹配关键词
        if dimension:
            rows = self._conn.execute(
                "SELECT label FROM aesthetic_prefs WHERE dimension=?",
                (dimension,)
            ).fetchall()
            for r in rows:
                label = r["label"]
                if label in stimulus:
                    return label
            # 如果 dimension 就是 label（不带冒号），直接用它
            return dimension

        return None

    def close(self):
        """关闭数据库连接。"""
        self._conn.close()
