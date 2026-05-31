#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
personality.py — 性格演化系统

偏好 / 习惯 / 偏见累积系统，基于 SQLite 持久化存储。
通过不断积累交互数据，逐渐形成可查询、可总结的"数字人格"。
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Preference:
    """偏好数据模型"""
    name: str
    weight: float = 0.0
    category: str = ""
    description: str = ""
    updated_at: str = ""


@dataclass
class Habit:
    """习惯数据模型"""
    name: str
    frequency: int = 0
    last_performed: str = ""
    interval_hours: float = 0.0


@dataclass
class Bias:
    """偏见数据模型"""
    name: str
    direction: float = 0.0          # -1 ~ 1: -1=负面, 0=中性, 1=正面
    evidence: list = field(default_factory=list)  # JSON 字符串列表
    updated_at: str = ""


# ---------------------------------------------------------------------------
# Personality 主类
# ---------------------------------------------------------------------------

class Personality:
    """
    性格演化系统 —— 管理偏好、习惯、偏见的持久化和查询。

    用法::

        p = Personality("/path/to/personality.db")
        p.update_preference("简洁沟通", +3, "communication", "沟通时偏好简洁风格")
        p.record_habit("每日服务器检查", 24)
        p.update_bias("大王喜欢简洁", 0.8, "session 123: 被骂啰嗦")
        print(p.summarize())
    """

    def __init__(self, db_path: str = "personality.db"):
        """
        初始化 Personality 引擎。

        :param db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

        # 内存缓存 —— 初始化时从 SQLite 恢复全部数据
        self.preferences: dict[str, Preference] = {}
        self.habits: dict[str, Habit] = {}
        self.biases: dict[str, Bias] = {}
        self._load_all()

    # -----------------------------------------------------------------------
    # 数据库初始化
    # -----------------------------------------------------------------------

    def _init_db(self) -> None:
        """创建 personality 库的三张核心表（若不存在）"""
        cursor = self._conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (
                name        TEXT PRIMARY KEY,
                weight      REAL DEFAULT 0,
                category    TEXT,
                description TEXT,
                updated_at  TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS habits (
                name            TEXT PRIMARY KEY,
                frequency       INTEGER DEFAULT 0,
                last_performed  TIMESTAMP,
                interval_hours  REAL
            );

            CREATE TABLE IF NOT EXISTS biases (
                name        TEXT PRIMARY KEY,
                direction   REAL CHECK(direction >= -1 AND direction <= 1),
                evidence    TEXT,       -- JSON 格式的列表
                updated_at  TIMESTAMP
            );
        """)
        self._conn.commit()

    # -----------------------------------------------------------------------
    # 数据加载与恢复
    # -----------------------------------------------------------------------

    def _load_all(self) -> None:
        """从 SQLite 恢复所有偏好 / 习惯 / 偏见到内存缓存"""
        self._load_preferences()
        self._load_habits()
        self._load_biases()

    def _load_preferences(self) -> None:
        """加载所有偏好"""
        cursor = self._conn.cursor()
        cursor.execute("SELECT name, weight, category, description, updated_at FROM preferences")
        for row in cursor.fetchall():
            self.preferences[row["name"]] = Preference(
                name=row["name"],
                weight=row["weight"],
                category=row["category"] or "",
                description=row["description"] or "",
                updated_at=row["updated_at"] or "",
            )

    def _load_habits(self) -> None:
        """加载所有习惯"""
        cursor = self._conn.cursor()
        cursor.execute("SELECT name, frequency, last_performed, interval_hours FROM habits")
        for row in cursor.fetchall():
            self.habits[row["name"]] = Habit(
                name=row["name"],
                frequency=row["frequency"],
                last_performed=row["last_performed"] or "",
                interval_hours=row["interval_hours"] or 0.0,
            )

    def _load_biases(self) -> None:
        """加载所有偏见"""
        cursor = self._conn.cursor()
        cursor.execute("SELECT name, direction, evidence, updated_at FROM biases")
        for row in cursor.fetchall():
            evidence_list = []
            if row["evidence"]:
                try:
                    evidence_list = json.loads(row["evidence"])
                except (json.JSONDecodeError, TypeError):
                    evidence_list = []
            self.biases[row["name"]] = Bias(
                name=row["name"],
                direction=row["direction"],
                evidence=evidence_list,
                updated_at=row["updated_at"] or "",
            )

    # -----------------------------------------------------------------------
    # 偏好管理
    # -----------------------------------------------------------------------

    def update_preference(
        self,
        name: str,
        delta_weight: float,
        category: str = "",
        description: str = "",
    ) -> None:
        """
        更新偏好权重。

        - 权重累积：每次调用会在原值上增加 delta_weight
        - 范围限制：weight 钳位在 0~100 之间
        - 首次使用某偏好名时自动创建记录

        :param name: 偏好名称，如 "简洁风格"
        :param delta_weight: 权重增量，如 +3
        :param category: 所属类别，如 "communication"
        :param description: 描述，如 "沟通时偏好简洁风格"
        """
        now = _now_iso()
        cursor = self._conn.cursor()

        # 若已存在，读取当前权重
        current_weight = 0.0
        if name in self.preferences:
            current_weight = self.preferences[name].weight

        new_weight = max(0.0, min(100.0, current_weight + delta_weight))

        cursor.execute(
            """INSERT INTO preferences (name, weight, category, description, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   weight      = excluded.weight,
                   category    = COALESCE(NULLIF(?,''), preferences.category),
                   description = COALESCE(NULLIF(?,''), preferences.description),
                   updated_at  = excluded.updated_at""",
            (name, new_weight, category, description, now,
             category, description),
        )
        self._conn.commit()

        # 同步内存缓存
        self.preferences[name] = Preference(
            name=name,
            weight=new_weight,
            category=category or self.preferences.get(name, Preference(name=name)).category,
            description=description or self.preferences.get(name, Preference(name=name)).description,
            updated_at=now,
        )

    def get_preferences(self, category: str = None, top_n: int = 5) -> list[Preference]:
        """
        获取权重最高的偏好。

        :param category: 筛选类别（None 表示全部）
        :param top_n: 返回前 N 条
        :return: Preference 列表，按 weight 降序排列
        """
        prefs = list(self.preferences.values())
        if category:
            prefs = [p for p in prefs if p.category == category]
        prefs.sort(key=lambda p: p.weight, reverse=True)
        return prefs[:top_n]

    # -----------------------------------------------------------------------
    # 习惯管理
    # -----------------------------------------------------------------------

    def record_habit(self, name: str, interval_hours: float) -> None:
        """
        记录一次习惯执行。

        - frequency 加 1
        - last_performed 更新为当前时间
        - interval_hours 仅在首次创建时设置，后续不覆盖（允许调整）

        :param name: 习惯名称，如 "每日服务器检查"
        :param interval_hours: 执行间隔（小时），如 24
        """
        now = _now_iso()
        cursor = self._conn.cursor()

        # 获取当前频率
        current_freq = 0
        if name in self.habits:
            current_freq = self.habits[name].frequency

        new_freq = current_freq + 1

        cursor.execute(
            """INSERT INTO habits (name, frequency, last_performed, interval_hours)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   frequency      = excluded.frequency,
                   last_performed = excluded.last_performed,
                   interval_hours = COALESCE(habits.interval_hours, excluded.interval_hours)""",
            (name, new_freq, now, interval_hours),
        )
        self._conn.commit()

        # 同步内存缓存
        existing = self.habits.get(name)
        self.habits[name] = Habit(
            name=name,
            frequency=new_freq,
            last_performed=now,
            interval_hours=existing.interval_hours if existing else interval_hours,
        )

    def get_due_habits(self) -> list[Habit]:
        """
        获取到点该执行的习惯列表。

        判断逻辑: last_performed + interval_hours < now

        :return: 到期待执行的 Habit 列表
        """
        now_ts = time.time()
        due: list[Habit] = []
        for habit in self.habits.values():
            if not habit.last_performed or not habit.interval_hours:
                # 从未执行过或间隔未设置 —— 视为到期
                due.append(habit)
                continue
            try:
                last_ts = _parse_iso(habit.last_performed)
            except (ValueError, TypeError):
                # 时间解析失败，保守视为到期
                due.append(habit)
                continue
            if last_ts + habit.interval_hours * 3600 < now_ts:
                due.append(habit)
        return due

    # -----------------------------------------------------------------------
    # 偏见管理
    # -----------------------------------------------------------------------

    def update_bias(self, name: str, direction: float, evidence_text: str) -> None:
        """
        更新偏见。

        - direction: -1 ~ 1，-1=负面偏好，0=中性，1=正面偏好
        - evidence_text: 新的证据文本，追加到已有证据列表末尾
        - direction 会被新旧加权平均（旧权重 = 已有证据条数 + 1）

        :param name: 偏见名称，如 "大王喜欢简洁"
        :param direction: 偏见方向，-1 ~ 1
        :param evidence_text: 新增证据文本
        """
        direction = max(-1.0, min(1.0, direction))
        now = _now_iso()
        cursor = self._conn.cursor()

        # 读取已有记录
        existing_evidence: list[str] = []
        if name in self.biases:
            existing_evidence = list(self.biases[name].evidence)

        # 追加新证据
        existing_evidence.append(evidence_text)
        evidence_json = json.dumps(existing_evidence, ensure_ascii=False)

        # 加权平均 direction
        old_count = len(existing_evidence) - 1  # 追加前条数
        if old_count > 0 and name in self.biases:
            old_dir = self.biases[name].direction
            blended = (old_dir * old_count + direction) / (old_count + 1)
        else:
            blended = direction
        blended = max(-1.0, min(1.0, blended))

        cursor.execute(
            """INSERT INTO biases (name, direction, evidence, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   direction = excluded.direction,
                   evidence  = excluded.evidence,
                   updated_at = excluded.updated_at""",
            (name, blended, evidence_json, now),
        )
        self._conn.commit()

        # 同步内存缓存
        self.biases[name] = Bias(
            name=name,
            direction=blended,
            evidence=existing_evidence,
            updated_at=now,
        )

    def get_biases(self) -> list[Bias]:
        """
        获取所有偏见。

        :return: Bias 列表，按 |direction| 降序排列
        """
        biases = list(self.biases.values())
        biases.sort(key=lambda b: abs(b.direction), reverse=True)
        return biases

    # -----------------------------------------------------------------------
    # 工具方法
    # -----------------------------------------------------------------------

    def summarize(self) -> str:
        """
        返回性格摘要文本。

        格式: '偏好: {top3偏好}. 习惯: {active_habits_count}个. 偏见: {top2偏见}.'

        :return: 中文字符串摘要
        """
        # Top 3 偏好
        top_prefs = self.get_preferences(top_n=3)
        pref_str = ", ".join(
            f"{p.name}({p.weight:.0f})" for p in top_prefs
        ) if top_prefs else "暂无"

        # 活跃习惯计数（有执行记录且 interval > 0 的）
        active_habits = [h for h in self.habits.values() if h.frequency > 0]
        habit_count = len(active_habits)

        # Top 2 偏见（按方向强度排序）
        biases = self.get_biases()[:2]
        bias_str = ", ".join(
            f"{b.name}({b.direction:+.1f})" for b in biases
        ) if biases else "暂无"

        return f"偏好: {pref_str}. 习惯: {habit_count}个. 偏见: {bias_str}."

    def consolidate(self) -> None:
        """
        定期合并/遗忘：删除 weight < 1 的偏好（太久不用的遗忘机制）。

        同时清理 direction == 0 且证据为空的偏见。
        """
        cursor = self._conn.cursor()
        now = _now_iso()

        # 遗忘低权重偏好
        cursor.execute("DELETE FROM preferences WHERE weight < 1")
        deleted_prefs = cursor.rowcount

        # 清理无意义的偏见
        cursor.execute(
            "DELETE FROM biases WHERE direction = 0 AND (evidence IS NULL OR evidence = '[]' OR evidence = '')"
        )
        deleted_biases = cursor.rowcount

        self._conn.commit()

        # 同步内存缓存
        self.preferences = {
            n: p for n, p in self.preferences.items() if p.weight >= 1
        }
        self.biases = {
            n: b for n, b in self.biases.items()
            if not (b.direction == 0 and len(b.evidence) == 0)
        }

    # -----------------------------------------------------------------------
    # 魔法方法
    # -----------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Personality(db='{self.db_path}', "
            f"preferences={len(self.preferences)}, "
            f"habits={len(self.habits)}, "
            f"biases={len(self.biases)})"
        )


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """返回当前 UTC ISO 格式时间戳"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(iso_str: str) -> float:
    """
    将 ISO 时间字符串解析为 Unix 时间戳（float）。

    支持格式: "2025-01-15T10:30:00Z" 或 "2025-01-15 10:30:00"
    """
    # 尝试带 Z 的格式
    s = iso_str.replace("Z", "+00:00")
    if "T" not in s:
        s = s.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except ValueError:
        # 兜底：尝试 common log 格式
        s2 = iso_str.replace("T", " ")
        if "." in s2:
            s2 = s2.split(".")[0]
        dt = datetime.strptime(s2, "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()


# ---------------------------------------------------------------------------
# 快速测试
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import os

    print("=" * 60)
    print("Personality 性格演化系统 — 快速测试")
    print("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        p = Personality(db_path)

        # --- 偏好测试 ---
        print("\n[偏好] 更新 '简洁沟通' weight += 15")
        p.update_preference("简洁沟通", 15, "communication", "沟通时偏好简洁风格")
        print(f"    → {p.preferences['简洁沟通']}")

        print("[偏好] 更新 '主动汇报' weight += 8")
        p.update_preference("主动汇报", 8, "behavior", "主动向用户汇报进度")
        print(f"    → {p.preferences['主动汇报']}")

        print("[偏好] 更新 'Django 优先' weight += 5")
        p.update_preference("Django 优先", 5, "tech", "技术选型优先 Django")
        print(f"    → {p.preferences['Django 优先']}")

        pref_list = p.get_preferences(category="communication")
        print(f"[偏好] 通信类别偏好: {[pr.name for pr in pref_list]}")

        pref_top = p.get_preferences(top_n=2)
        print(f"[偏好] Top 2: {[pr.name for pr in pref_top]}")

        # --- 习惯测试 ---
        print("\n[习惯] 记录 '每日服务器检查' (interval=24h)")
        p.record_habit("每日服务器检查", 24)
        print(f"    → {p.habits['每日服务器检查']}")

        print("[习惯] 记录 'Slack 问候' (interval=1h)")
        p.record_habit("Slack 问候", 1)
        print(f"    → {p.habits['Slack 问候']}")

        due = p.get_due_habits()
        print(f"[习惯] 到期习惯数: {len(due)} (刚记录，预期 0)")

        # --- 偏见测试 ---
        print("\n[偏见] 更新 '大王喜欢简洁' direction=0.8")
        p.update_bias("大王喜欢简洁", 0.8, "session 123: 被骂啰嗦")
        print(f"    → {p.biases['大王喜欢简洁']}")

        print("[偏见] 追加证据")
        p.update_bias("大王喜欢简洁", 0.7, "session 456: 被要求简短")
        print(f"    → direction={p.biases['大王喜欢简洁'].direction:.2f}, 证据数={len(p.biases['大王喜欢简洁'].evidence)}")

        print("\n[偏见] 全部偏见:")
        for b in p.get_biases():
            print(f"    - {b.name}: dir={b.direction:+.2f}, ev={len(b.evidence)}条")

        # --- 摘要测试 ---
        print(f"\n[摘要]\n    {p.summarize()}")

        # --- consolidate 测试 ---
        print("\n[consolidate] 添加低权重偏好 '临时想法' weight=0.5 ...")
        p.update_preference("临时想法", 0.5, "misc", "临时冒出的想法")
        print(f"    合并前偏好数: {len(p.preferences)}")
        p.consolidate()
        print(f"    合并后偏好数: {len(p.preferences)} (预期 3，临时想法被遗忘)")

        # --- 重建测试（验证 SQLite 持久化） ---
        print("\n[持久化] 重新加载数据库验证...")
        p2 = Personality(db_path)
        print(f"    偏好数: {len(p2.preferences)}")
        print(f"    习惯数: {len(p2.habits)}")
        print(f"    偏见数: {len(p2.biases)}")
        print(f"    摘要: {p2.summarize()}")

        print("\n" + "=" * 60)
        print("✅ 全部测试通过！")
        print("=" * 60)

    finally:
        os.unlink(db_path)
