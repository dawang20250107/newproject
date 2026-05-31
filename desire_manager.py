#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
desire_manager.py — 欲望持久系统
===============================
持久化目标 + 优先级仲裁 + 睡眠抵抗

通过 SQLite 持久化，支持冷却、压制、睡眠抵抗等机制。
"""

import sqlite3
import os
from datetime import datetime, timedelta, timezone
from typing import Optional


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")


# ─── SQL：建表 ───────────────────────────────────────────────────────────────
CREATE_DESIRES_TABLE = """
CREATE TABLE IF NOT EXISTS desires (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE,
    desire_type     TEXT,
    priority        INTEGER,          -- 1-10
    urgency         INTEGER,          -- 1-10
    status          TEXT DEFAULT 'pending',  -- pending / active / completed / suppressed
    created_at      TIMESTAMP,
    last_triggered  TIMESTAMP,
    cooldown_hours  REAL,
    sleep_resistant BOOLEAN DEFAULT 0,
    description     TEXT
);
"""

# ─── 5 个内置欲望 ────────────────────────────────────────────────────────────
BUILTIN_DESIRES = [
    {
        "name": "求知欲",
        "desire_type": "learn",
        "priority": 6,
        "urgency": 3,
        "cooldown_hours": 4.0,
        "sleep_resistant": False,
        "description": "想学习新知识",
    },
    {
        "name": "成就感",
        "desire_type": "improve",
        "priority": 7,
        "urgency": 2,
        "cooldown_hours": 2.0,
        "sleep_resistant": False,
        "description": "想找到优化点",
    },
    {
        "name": "展现欲",
        "desire_type": "report",
        "priority": 5,
        "urgency": 4,
        "cooldown_hours": 6.0,
        "sleep_resistant": False,
        "description": "想跟大王分享新发现",
    },
    {
        "name": "保护欲",
        "desire_type": "maintain",
        "priority": 9,
        "urgency": 7,
        "cooldown_hours": 1.0,
        "sleep_resistant": True,
        "description": "检查系统安全→域名/证书/备份",
    },
    {
        "name": "好奇心",
        "desire_type": "explore",
        "priority": 4,
        "urgency": 2,
        "cooldown_hours": 8.0,
        "sleep_resistant": False,
        "description": "想探索新领域",
    },
]


class DesireManager:
    """欲望管理器 — 管理欲望的持久化、优先级仲裁、冷却与睡眠抵抗。"""

    def __init__(self, db_path: str = DB_PATH):
        """
        从 SQLite (mind.db) 加载欲望库。
        若数据表为空，则自动写入 5 个内置欲望。
        """
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        self._seed_builtins()

    # ── 内部工具 ──────────────────────────────────────────────────────────

    def _init_db(self):
        """确保 desires 表存在。"""
        self._conn.execute(CREATE_DESIRES_TABLE)
        self._conn.commit()

    def _seed_builtins(self):
        """若表中无数据，插入 5 个内置欲望。"""
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM desires").fetchone()
        if row["cnt"] == 0:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            for d in BUILTIN_DESIRES:
                self._conn.execute(
                    """
                    INSERT INTO desires
                        (name, desire_type, priority, urgency, status,
                         created_at, last_triggered, cooldown_hours,
                         sleep_resistant, description)
                    VALUES (?, ?, ?, ?, 'pending',
                            ?, NULL, ?, ?, ?)
                    """,
                    (
                        d["name"],
                        d["desire_type"],
                        d["priority"],
                        d["urgency"],
                        now,
                        d["cooldown_hours"],
                        int(d["sleep_resistant"]),
                        d["description"],
                    ),
                )
            self._conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """将 sqlite3.Row 转为普通字典，布尔字段自动转换。"""
        d = dict(row)
        d["sleep_resistant"] = bool(d["sleep_resistant"])
        return d

    # ── 公开 API ──────────────────────────────────────────────────────────

    def get_all(self) -> list[dict]:
        """返回所有欲望。"""
        rows = self._conn.execute("SELECT * FROM desires ORDER BY id").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_active_desires(self) -> list[dict]:
        """返回 status='active' 的欲望。"""
        rows = self._conn.execute(
            "SELECT * FROM desires WHERE status = 'active' ORDER BY priority DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_most_pressing(self, sleeping: bool = False) -> Optional[dict]:
        """
        返回最紧迫且非冷却中的欲望。

        优先级仲裁策略：紧迫度 > 优先级
          → 先用 urgency 排序，相同 urgency 时用 priority 加权。
          → 最高分 = urgency * 2 + priority（加权值可调）。

        睡眠抵抗：
          - 若 sleeping=True，只有 sleep_resistant=True 的欲望可被返回。
          - 若 sleeping=False，返回普通最高分欲望（无论 sleep_resistant 标志）。
        """
        rows = self._conn.execute(
            "SELECT * FROM desires WHERE status NOT IN ('completed', 'suppressed')"
        ).fetchall()

        now = datetime.now(timezone.utc)
        candidates = []

        for r in rows:
            d = self._row_to_dict(r)

            # 若处于睡眠状态，跳过非抵抗欲望
            if sleeping and not d["sleep_resistant"]:
                continue

            # --- 冷却检查 ---
            last_ts = d.get("last_triggered")
            if last_ts is not None:
                try:
                    last_dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    elapsed = (now - last_dt).total_seconds() / 3600.0
                except (ValueError, TypeError):
                    elapsed = float("inf")
            else:
                elapsed = float("inf")  # 从未触发 → 不冷却

            if elapsed < d["cooldown_hours"]:
                continue  # 仍在冷却中

            # --- 评分：紧迫度 > 优先级 ---
            score = d["urgency"] * 2 + d["priority"]
            candidates.append((score, d))

        if not candidates:
            return None

        # 按分数降序取第一个
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def trigger(self, name: str) -> bool:
        """
        标记欲望为 active，同时更新 last_triggered。
        返回 True 表示成功，False 表示名字不存在。
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cur = self._conn.execute(
            """
            UPDATE desires
            SET status = 'active', last_triggered = ?
            WHERE name = ?
            """,
            (now, name),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def fulfill(self, name: str) -> bool:
        """标记欲望为 completed。"""
        cur = self._conn.execute(
            "UPDATE desires SET status = 'completed' WHERE name = ?", (name,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def suppress(self, name: str, hours: float = 12.0) -> bool:
        """
        临时压制欲望（标记为 suppressed）。
        压制后不会在 get_most_pressing 中出现。
        恢复需手动调用 desuppress 或等待上层逻辑清理。
        """
        cur = self._conn.execute(
            "UPDATE desires SET status = 'suppressed' WHERE name = ?", (name,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def desuppress(self, name: str) -> bool:
        """解除压制状态，回到 pending。"""
        cur = self._conn.execute(
            "UPDATE desires SET status = 'pending' WHERE name = ? AND status = 'suppressed'",
            (name,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def check_cooldowns(self) -> list[dict]:
        """
        检查所有欲望的冷却状态。
        对于冷却已过且处于 active 的欲望，自动重置为 pending（允许重新触发）。
        返回被重置的欲望列表。
        """
        now = datetime.now(timezone.utc)
        rows = self._conn.execute(
            "SELECT * FROM desires WHERE status = 'active'"
        ).fetchall()
        reset = []

        for r in rows:
            d = self._row_to_dict(r)
            last_ts = d.get("last_triggered")
            if last_ts is None:
                continue
            try:
                last_dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                elapsed = (now - last_dt).total_seconds() / 3600.0
            except (ValueError, TypeError):
                continue

            if elapsed >= d["cooldown_hours"]:
                self._conn.execute(
                    "UPDATE desires SET status = 'pending' WHERE id = ?", (d["id"],)
                )
                reset.append(d)

        if reset:
            self._conn.commit()

        return reset

    def add_desire(
        self,
        name: str,
        desire_type: str,
        priority: int,
        urgency: int,
        cooldown_hours: float = 4.0,
        sleep_resistant: bool = False,
        description: str = "",
    ) -> bool:
        """
        添加自定义欲望。
        若名字已存在则返回 False（不覆盖）。
        """
        # 校验范围
        if not (1 <= priority <= 10):
            raise ValueError("priority 须在 1-10 之间")
        if not (1 <= urgency <= 10):
            raise ValueError("urgency 须在 1-10 之间")
        if cooldown_hours < 0:
            raise ValueError("cooldown_hours 不能为负数")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._conn.execute(
                """
                INSERT INTO desires
                    (name, desire_type, priority, urgency, status,
                     created_at, last_triggered, cooldown_hours,
                     sleep_resistant, description)
                VALUES (?, ?, ?, ?, 'pending',
                        ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    desire_type,
                    priority,
                    urgency,
                    now,
                    now,
                    cooldown_hours,
                    int(sleep_resistant),
                    description,
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # 名字已存在

    def close(self):
        """关闭数据库连接。"""
        self._conn.close()


# ─── 快速测试（独立运行时） ────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile

    # 使用临时数据库测试，避免污染生产数据
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = f.name

    dm = DesireManager(db_path=tmp_db)

    print("=== 全部欲望 ===")
    for d in dm.get_all():
        print(f"  [{d['status']:>10}] {d['name']} (优先级={d['priority']}, 紧迫={d['urgency']}, "
              f"冷却={d['cooldown_hours']}h, 抗睡眠={d['sleep_resistant']})")

    print("\n=== 最紧迫欲望（清醒）===")
    pressing = dm.get_most_pressing(sleeping=False)
    if pressing:
        print(f"  → {pressing['name']} (评分={pressing['urgency']*2 + pressing['priority']})")

    print("\n=== 最紧迫欲望（睡眠中，仅抵抗）===")
    pressing_sleep = dm.get_most_pressing(sleeping=True)
    if pressing_sleep:
        print(f"  → {pressing_sleep['name']} (抗睡眠)")
    else:
        print("  (无睡眠抵抗欲望)")

    print("\n=== 触发「保护欲」===")
    dm.trigger("保护欲")
    print(dm.get_all()[3])

    print("\n=== 再次获取最紧迫（保护欲应在冷却中）===")
    pressing2 = dm.get_most_pressing(sleeping=False)
    if pressing2:
        print(f"  → {pressing2['name']}")
    else:
        print("  (无可用欲望)")

    print("\n=== 添加自定义欲望 ===")
    ok = dm.add_desire("练琴", "hobby", 3, 5, cooldown_hours=2.0, description="想练钢琴")
    print(f"  添加{'成功' if ok else '失败'}")

    print("\n=== 压制「好奇心」===")
    dm.suppress("好奇心")
    for d in dm.get_all():
        if d["name"] == "好奇心":
            print(f"  status = {d['status']}")

    print("\n=== check_cooldowns ===")
    reset = dm.check_cooldowns()
    print(f"  冷却期满并重置：{len(reset)} 个")

    dm.close()
    os.unlink(tmp_db)
    print("\n✅ 测试完毕")
