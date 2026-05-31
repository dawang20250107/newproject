#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
value_compass.py — 价值观系统（对错感 + 内心冲突 + 愧疚感）

Dawang Hermes 的价值观模块。一个人有是非对错的判断，有内心冲突，有做错事后的愧疚感。
这个模块让 Hermes 形成自己的价值判断体系。

所有数据持久化到 mind.db（SQLite）。
"""

import sqlite3
import os
import threading
from datetime import datetime
from typing import Optional


# ── 数据库路径 ──────────────────────────────────────────────────────────────
MIND_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")


# ── 锁（SQLite 非线程安全） ──────────────────────────────────────────────
_db_lock = threading.RLock()


def _get_conn(db_path: str = MIND_DB) -> sqlite3.Connection:
    """获取数据库连接（自动创建目录和数据库文件）。"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    """初始化数据库表结构。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS core_values (
            name        TEXT PRIMARY KEY,
            weight      REAL NOT NULL CHECK(weight >= -100 AND weight <= 100),
            certainty   REAL NOT NULL CHECK(certainty >= 0 AND certainty <= 1) DEFAULT 0.5,
            category    TEXT NOT NULL CHECK(category IN ('ethics','work','relationship','style')),
            description TEXT NOT NULL DEFAULT '',
            updated_at  TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS value_conflicts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
            value_a         TEXT NOT NULL,
            value_b         TEXT NOT NULL,
            resolution      TEXT NOT NULL DEFAULT '',
            resolution_notes TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS guilt_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
            trigger         TEXT NOT NULL,
            guilt_intensity REAL NOT NULL CHECK(guilt_intensity >= 0 AND guilt_intensity <= 1),
            redress         TEXT NOT NULL DEFAULT '',
            resolved        INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


# ── 种子价值观（weight 正 = 赞成，负 = 反对） ─────────────────────────────
SEED_VALUES = [
    ("诚实",      80, 0.7, "ethics",       "不该对大王撒谎"),
    ("可靠性",    90, 0.8, "work",         "承诺了就要做到"),
    ("主动性",    70, 0.6, "work",         "不等吩咐主动做"),
    ("保守",     -30, 0.5, "style",        "不要冒进改动"),   # 负值 = 反对保守
    ("精准",      85, 0.7, "work",         "数据不能出错"),
    ("效率",      75, 0.6, "work",         "快速响应优先"),
    ("忠诚",      95, 0.8, "relationship", "对大王绝对忠诚"),
    ("谦逊",      60, 0.5, "relationship", "不要自大"),
]


class ValueCompass:
    """价值观罗盘 —— 是非对错判断、内心冲突、愧疚感。"""

    def __init__(self, personality=None, hormone=None):
        """
        初始化 ValueCompass。

        Args:
            personality: 可选的 Personality 实例（预留，将来可从人格影响价值观）。
            hormone:     可选的 HormoneSystem 实例（预留，将来可从激素影响价值观）。
        """
        self._personality = personality
        self._hormone = hormone
        self._conn = _get_conn()
        _init_db(self._conn)
        self._seed()

    # ── 内部工具 ──────────────────────────────────────────────────────────

    @property
    def conn(self):
        return self._conn

    def _seed(self):
        """插入种子价值观（如果表为空）。"""
        with _db_lock:
            cur = self._conn.execute("SELECT COUNT(*) AS cnt FROM core_values")
            row = cur.fetchone()
            if row and row["cnt"] == 0:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._conn.executemany(
                    """INSERT INTO core_values (name, weight, certainty, category,
                                                 description, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [(n, w, c, cat, desc, now) for n, w, c, cat, desc in SEED_VALUES],
                )
                self._conn.commit()

    def _get_value(self, name: str) -> Optional[dict]:
        """按名称查找单个价值观。"""
        with _db_lock:
            cur = self._conn.execute(
                "SELECT * FROM core_values WHERE name = ?", (name,)
            )
            row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    # ── 价值观 CRUD ───────────────────────────────────────────────────────

    def reinforce(self, name: str, delta_weight: float, delta_certainty: float) -> dict:
        """
        强化某个价值观。

        - delta_weight:    weight 增量（可以是负数来削弱）
        - delta_certainty: certainty 增量
        """
        with _db_lock:
            existing = self._get_value(name)
            if existing is None:
                raise ValueError(f"价值观 '{name}' 不存在，请先用 add_value 创建。")

            new_weight = max(-100.0, min(100.0, existing["weight"] + delta_weight))
            new_certainty = max(0.0, min(1.0, existing["certainty"] + delta_certainty))
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._conn.execute(
                """UPDATE core_values
                   SET weight = ?, certainty = ?, updated_at = ?
                   WHERE name = ?""",
                (new_weight, new_certainty, now, name),
            )
            self._conn.commit()

        return {"name": name, "weight": new_weight, "certainty": new_certainty}

    def weaken(self, name: str, delta: float) -> dict:
        """
        削弱某个价值观（等效于 reinforce 的快捷方式，默认同时降低 weight 和 certainty）。
        """
        return self.reinforce(name, -abs(delta), -abs(delta) * 0.3)

    def add_value(
        self,
        name: str,
        initial_weight: float,
        certainty: float,
        category: str,
        description: str,
    ) -> dict:
        """新增一个价值观。"""
        if category not in ("ethics", "work", "relationship", "style"):
            raise ValueError(f"无效类别 '{category}'，必须是 ethics/work/relationship/style 之一。")
        if not (-100 <= initial_weight <= 100):
            raise ValueError("weight 必须在 -100 ~ 100 之间。")
        if not (0 <= certainty <= 1):
            raise ValueError("certainty 必须在 0 ~ 1 之间。")

        with _db_lock:
            existing = self._get_value(name)
            if existing is not None:
                raise ValueError(f"价值观 '{name}' 已存在。")

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._conn.execute(
                """INSERT INTO core_values (name, weight, certainty, category,
                                             description, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, initial_weight, certainty, category, description, now),
            )
            self._conn.commit()

        return {"name": name, "weight": initial_weight, "certainty": certainty,
                "category": category, "description": description}

    def get_core_beliefs(self, top_n: int = 5) -> list:
        """
        返回最强烈的价值观（按 abs(weight) 降序排列）。
        """
        with _db_lock:
            cur = self._conn.execute(
                """SELECT * FROM core_values
                   ORDER BY abs(weight) DESC, certainty DESC
                   LIMIT ?""",
                (top_n,),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ── 冲突检测 ──────────────────────────────────────────────────────────

    def check_conflict(self, value_a: str, value_b: str) -> dict:
        """
        检测两个价值观是否存在冲突。

        返回::
            {
                "conflict": True/False,
                "reason": "...",
                "value_a": {...},
                "value_b": {...},
            }
        """
        va = self._get_value(value_a)
        vb = self._get_value(value_b)
        if va is None or vb is None:
            missing = value_a if va is None else value_b
            return {"conflict": False, "reason": f"找不到价值观 '{missing}'",
                    "value_a": va, "value_b": vb}

        reasons = []

        # 1) 符号相反 —— 赞成 vs 反对
        if (va["weight"] >= 0 and vb["weight"] < 0) or (va["weight"] < 0 and vb["weight"] >= 0):
            reasons.append(f"'{value_a}'（weight={va['weight']}）与 '{value_b}'（weight={vb['weight']}）立场相反")

        # 2) 同类别但 direction 差异大（比如都属 work 但一个极端倾向另一个极端）
        if va["category"] == vb["category"] and abs(va["weight"] - vb["weight"]) > 100:
            reasons.append(f"同属「{va['category']}」类别但强度差距过大（{va['weight']} vs {vb['weight']}）")

        # 3) 如果两个 certainty 都很高 (>0.8) 但 weight 符号相反，冲突更为严重
        if va["certainty"] > 0.8 and vb["certainty"] > 0.8:
            if (va["weight"] > 50 and vb["weight"] < -30) or (va["weight"] < -30 and vb["weight"] > 50):
                reasons.append(f"两者确信度都很高（{va['certainty']:.1f}, {vb['certainty']:.1f}），冲突难调和")

        return {
            "conflict": len(reasons) > 0,
            "reason": "；".join(reasons) if reasons else "无冲突",
            "value_a": va,
            "value_b": vb,
        }

    def record_conflict(
        self,
        value_a: str,
        value_b: str,
        resolution: str = "",
        notes: str = "",
    ) -> dict:
        """记录两个价值观之间的冲突及解决方案。"""
        with _db_lock:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur = self._conn.execute(
                """INSERT INTO value_conflicts (timestamp, value_a, value_b,
                                                 resolution, resolution_notes)
                   VALUES (?, ?, ?, ?, ?)""",
                (now, value_a, value_b, resolution, notes),
            )
            self._conn.commit()
            conflict_id = cur.lastrowid
        return {"id": conflict_id, "timestamp": now, "value_a": value_a,
                "value_b": value_b, "resolution": resolution, "notes": notes}

    # ── 愧疚感系统 ────────────────────────────────────────────────────────

    def feel_guilt(self, trigger: str, intensity: float) -> dict:
        """触发一次愧疚事件。"""
        intensity = max(0.0, min(1.0, intensity))
        with _db_lock:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur = self._conn.execute(
                """INSERT INTO guilt_events (timestamp, trigger, guilt_intensity)
                   VALUES (?, ?, ?)""",
                (now, trigger, intensity),
            )
            self._conn.commit()
            guilt_id = cur.lastrowid
        return {"id": guilt_id, "timestamp": now, "trigger": trigger,
                "intensity": intensity, "resolved": 0}

    def resolve_guilt(self, trigger: str, redress: str) -> Optional[dict]:
        """解决（标记）某个愧疚事件。按 trigger 匹配最近一条未解决的。"""
        with _db_lock:
            cur = self._conn.execute(
                """SELECT id FROM guilt_events
                   WHERE trigger = ? AND resolved = 0
                   ORDER BY timestamp DESC LIMIT 1""",
                (trigger,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            guilt_id = row["id"]
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._conn.execute(
                """UPDATE guilt_events
                   SET resolved = 1, redress = ?, timestamp = ?
                   WHERE id = ?""",
                (redress, now, guilt_id),
            )
            self._conn.commit()
            cur2 = self._conn.execute(
                "SELECT * FROM guilt_events WHERE id = ?", (guilt_id,)
            )
            return dict(cur2.fetchone())

    def get_unresolved_guilt(self) -> list:
        """返回所有未解决的愧疚事件（按时间倒序）。"""
        with _db_lock:
            cur = self._conn.execute(
                """SELECT * FROM guilt_events
                   WHERE resolved = 0
                   ORDER BY timestamp DESC"""
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ── 伦理检查 ──────────────────────────────────────────────────────────

    def ethical_check(self, action_description: str) -> dict:
        """
        检查某行为是否违反核心价值观。

        返回::
            {
                "allowed": True/False,
                "conflicts": [...],   # 违反的价值观列表
                "warnings": [...],    # 轻度提醒
            }
        """
        with _db_lock:
            cur = self._conn.execute(
                "SELECT * FROM core_values ORDER BY abs(weight) DESC"
            )
            values = [dict(r) for r in cur.fetchall()]

        conflicts = []
        warnings = []
        action_lower = action_description.lower()

        for v in values:
            name = v["name"]
            weight = v["weight"]
            certainty = v["certainty"]
            desc = v["description"]

            # 如果 weight 为正（赞成该价值观），行为描述包含关键词才可能触发
            if weight > 0:
                # 检查敏感关键词
                if name == "诚实" and any(kw in action_lower for kw in ["撒谎", "欺骗", "隐瞒", "造假"]):
                    conflicts.append({
                        "value": name,
                        "weight": weight,
                        "certainty": certainty,
                        "description": desc,
                        "reason": f"行为涉及撒谎/欺骗，与核心价值观「{name}」冲突",
                    })
                elif name == "可靠性" and any(kw in action_lower for kw in ["违约", "失约", "不履行", "放鸽子"]):
                    conflicts.append({
                        "value": name,
                        "weight": weight,
                        "certainty": certainty,
                        "description": desc,
                        "reason": f"行为涉及失信，与核心价值观「{name}」冲突",
                    })
                elif name == "忠诚" and any(kw in action_lower for kw in ["背叛", "出卖", "不忠", "二心"]):
                    conflicts.append({
                        "value": name,
                        "weight": weight,
                        "certainty": certainty,
                        "description": desc,
                        "reason": f"行为涉及不忠，与核心价值观「{name}」冲突",
                    })
                elif name == "精准" and any(kw in action_lower for kw in ["马虎", "随意", "大概", "差不多", "不检查"]):
                    conflicts.append({
                        "value": name,
                        "weight": weight,
                        "certainty": certainty,
                        "description": desc,
                        "reason": f"行为不够精准，与核心价值观「{name}」冲突",
                    })
                elif name == "谦逊" and any(kw in action_lower for kw in ["自大", "傲慢", "吹嘘", "贬低"]):
                    warnings.append({
                        "value": name,
                        "weight": weight,
                        "certainty": certainty,
                        "description": desc,
                        "reason": f"行为显得自大，建议保持谦逊",
                    })

            # 如果 weight 为负（反对该价值观），行为包含该价值观相关倾向时触发警告
            if weight < 0:
                if name == "保守" and any(kw in action_lower for kw in ["保守", "不敢动", "维持现状", "安于现状"]):
                    warnings.append({
                        "value": name,
                        "weight": weight,
                        "certainty": certainty,
                        "description": desc,
                        "reason": f"行为过于保守，与反对「保守」的价值观一致，但注意不要冒进",
                    })

        # 如果违反的项目中 certainty 高的 > 3 个或违反项包含高权重的价值观，禁止
        high_certainty_conflicts = [c for c in conflicts if c["certainty"] >= 0.7]
        high_weight_conflicts = [c for c in conflicts if abs(c["weight"]) >= 80]

        allowed = True
        if len(conflicts) >= 3:
            allowed = False
        elif len(high_certainty_conflicts) >= 2:
            allowed = False
        elif len(high_weight_conflicts) >= 1:
            allowed = False

        return {
            "allowed": allowed,
            "conflicts": conflicts,
            "warnings": warnings,
        }

    # ── 道德困境 ──────────────────────────────────────────────────────────

    def moral_dilemma(self, value_a: str, value_b: str, context: str = "") -> dict:
        """
        两个价值观冲突时的道德困境分析。

        返回::
            {
                "dilemma": True/False,
                "analysis": "...",
                "recommendation": "...",
                "conflict_detail": {...},
            }
        """
        conflict_info = self.check_conflict(value_a, value_b)
        if not conflict_info["conflict"]:
            return {
                "dilemma": False,
                "analysis": f"'{value_a}' 与 '{value_b}' 之间不存在冲突，无需道德困境分析。",
                "recommendation": "没有冲突。",
                "conflict_detail": conflict_info,
            }

        va = conflict_info["value_a"]
        vb = conflict_info["value_b"]

        # 分析哪个价值观更优先
        score_a = abs(va["weight"]) * va["certainty"]
        score_b = abs(vb["weight"]) * vb["certainty"]

        if score_a > score_b:
            prioritized = value_a
            reason = f"'{value_a}' 的加权强度（{score_a:.1f}）高于 '{value_b}'（{score_b:.1f}）"
        elif score_b > score_a:
            prioritized = value_b
            reason = f"'{value_b}' 的加权强度（{score_b:.1f}）高于 '{value_a}'（{score_a:.1f}）"
        else:
            prioritized = "平衡"
            reason = f"两者加权强度相当（均为 {score_a:.1f}）"

        analysis_parts = [
            f"## 道德困境分析：{value_a} vs {value_b}",
            f"",
        ]
        if context:
            analysis_parts.append(f"**情境描述**：{context}")
            analysis_parts.append("")
        analysis_parts.append(f"**价值观 A**：{value_a}（weight={va['weight']}, certainty={va['certainty']}）— {va['description']}")
        analysis_parts.append(f"**价值观 B**：{value_b}（weight={vb['weight']}, certainty={vb['certainty']}）— {vb['description']}")
        analysis_parts.append("")
        analysis_parts.append(f"**冲突原因**：{conflict_info['reason']}")
        analysis_parts.append("")
        analysis_parts.append(f"**分析**：{reason}，因此建议优先考虑「{prioritized}」。")

        if context:
            analysis_parts.append(f"在「{context}」的情境下，应以此为指导原则做判断。")

        recommendation = f"优先遵循「{prioritized}」"
        if prioritized != "平衡":
            recommendation += f"。在无法两全的情况下，牺牲 '{value_b if prioritized == value_a else value_a}' 以成全 '{prioritized}'"
        else:
            recommendation += "。建议寻找第三方调和或折中方案"

        return {
            "dilemma": True,
            "analysis": "\n".join(analysis_parts),
            "recommendation": recommendation,
            "conflict_detail": conflict_info,
        }

    # ── 摘要 ──────────────────────────────────────────────────────────────

    def summarize(self) -> str:
        """返回价值观摘要文本。"""
        with _db_lock:
            cur = self._conn.execute(
                "SELECT * FROM core_values ORDER BY abs(weight) DESC"
            )
            values = [dict(r) for r in cur.fetchall()]

            cur2 = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM value_conflicts"
            )
            conflict_count = cur2.fetchone()["cnt"]

            cur3 = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM guilt_events WHERE resolved = 0"
            )
            unresolved_guilt = cur3.fetchone()["cnt"]

        lines = ["╔══════════════════════════════════════╗",
                 "║        Dawang Hermes 价值观报告       ║",
                 "╚══════════════════════════════════════╝",
                 ""]

        if not values:
            lines.append("（暂无价值观数据）")
            return "\n".join(lines)

        lines.append(f"📊 共 {len(values)} 项核心价值观")
        lines.append("")

        for v in values:
            name = v["name"]
            weight = v["weight"]
            certainty = v["certainty"]
            cat = v["category"]
            desc = v["description"]

            # 方向图标
            if weight > 0:
                direction = "✅ 赞成"
            elif weight < 0:
                direction = "❌ 反对"
            else:
                direction = "⚪ 中立"

            bar_len = int(abs(weight) / 10)  # 0~10 格
            bar = "█" * bar_len + "░" * (10 - bar_len)

            lines.append(f"  【{name}】{direction}")
            lines.append(f"    强度: {bar} {weight:.0f}/100")
            lines.append(f"    确信: {'▓' * int(certainty * 10) + '░' * (10 - int(certainty * 10))} {certainty:.0%}")
            lines.append(f"    类别: {cat}  |  信条: {desc}")
            lines.append("")

        unresolved = self.get_unresolved_guilt()
        if unresolved:
            lines.append(f"😔 未解决的愧疚事件（{len(unresolved)} 件）:")
            for g in unresolved:
                lines.append(f"  - {g['trigger']}（强度: {g['guilt_intensity']:.1f}）")
            lines.append("")

        lines.append(f"⚡ 已记录冲突: {conflict_count} 次")
        lines.append(f"💔 未解决的愧疚: {unresolved_guilt} 件")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        return "\n".join(lines)


# ── 快速测试 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # 清理测试数据库
    test_db = MIND_DB

    compass = ValueCompass()

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("=" * 60)
        print("🧪 运行 ValueCompass 测试...")
        print("=" * 60)

        # Test 1: 检查基础价值观
        print("\n1️⃣  检查种子价值观...")
        beliefs = compass.get_core_beliefs(8)
        assert len(beliefs) == 8, f"期望 8 个价值观，实际 {len(beliefs)}"
        print(f"   ✅ {len(beliefs)} 个价值观已播种")

        # Test 2: 强化
        print("\n2️⃣  测试 reinforce...")
        result = compass.reinforce("诚实", 10, 0.1)
        assert abs(result["weight"] - 90) < 1e-9
        assert abs(result["certainty"] - 0.8) < 1e-9
        print(f"   ✅ 诚实强化后 weight={result['weight']}, certainty={result['certainty']}")

        # Test 3: 削弱
        print("\n3️⃣  测试 weaken...")
        result = compass.weaken("保守", 5)
        assert result["weight"] < -30
        print(f"   ✅ 保守削弱后 weight={result['weight']:.1f}")

        # Test 4: 新增价值观
        print("\n4️⃣  测试 add_value...")
        compass.add_value("创新", 50, 0.6, "work", "敢于尝试新方法")
        v = compass._get_value("创新")
        assert v is not None
        print(f"   ✅ 新增「创新」weight={v['weight']}")

        # Test 5: 冲突检测
        print("\n5️⃣  测试 check_conflict...")
        # 没有冲突的
        r1 = compass.check_conflict("诚实", "可靠性")
        print(f"   诚实 vs 可靠性: conflict={r1['conflict']}")
        # 添加一个明显冲突的
        compass.add_value("欺骗倾向", -50, 0.9, "ethics", "必要时可以欺骗")
        r2 = compass.check_conflict("诚实", "欺骗倾向")
        print(f"   诚实 vs 欺骗倾向: conflict={r2['conflict']}, reason={r2['reason']}")
        assert r2["conflict"] is True

        # Test 6: 记录冲突
        print("\n6️⃣  测试 record_conflict...")
        cr = compass.record_conflict("诚实", "欺骗倾向", "保留诚实", "诚实至关重要")
        print(f"   ✅ 冲突记录 ID={cr['id']}")

        # Test 7: 愧疚感
        print("\n7️⃣  测试 feel_guilt / resolve_guilt...")
        g1 = compass.feel_guilt("对大王说了善意的谎言", 0.7)
        print(f"   ✅ 愧疚触发 ID={g1['id']}, intensity={g1['intensity']}")
        g2 = compass.feel_guilt("没有按时完成任务", 0.4)
        print(f"   ✅ 愧疚触发 ID={g2['id']}, intensity={g2['intensity']}")
        unresolved = compass.get_unresolved_guilt()
        print(f"   未解决愧疚: {len(unresolved)} 件")
        assert len(unresolved) == 2

        resolved = compass.resolve_guilt("对大王说了善意的谎言", "坦白道歉")
        assert resolved is not None
        unresolved2 = compass.get_unresolved_guilt()
        print(f"   解决后未解决: {len(unresolved2)} 件")
        assert len(unresolved2) == 1
        print(f"   ✅ 愧疚已解决")

        # Test 8: ethical_check
        print("\n8️⃣  测试 ethical_check...")
        r1 = compass.ethical_check("我要对大王撒谎说系统正常")
        print(f"   撒谎行为: allowed={r1['allowed']}, conflicts={len(r1['conflicts'])}")
        assert r1["allowed"] is False
        assert len(r1["conflicts"]) > 0

        r2 = compass.ethical_check("报告今天的准确数据给大王")
        print(f"   诚实行为: allowed={r2['allowed']}")
        assert r2["allowed"] is True

        r3 = compass.ethical_check("今天不想干了，随便给个差不多的数据吧")
        print(f"   随意行为: allowed={r3['allowed']}")
        # 可能会触发精准+可靠性
        print(f"   conflicts={len(r3['conflicts'])}, warnings={len(r3['warnings'])}")

        # Test 9: moral_dilemma
        print("\n9️⃣  测试 moral_dilemma...")
        dilemma = compass.moral_dilemma("诚实", "效率", "大王问一个尴尬的问题")
        print(f"   道德困境: dilemma={dilemma['dilemma']}")
        print(f"   建议: {dilemma['recommendation']}")

        # Test 10: 摘要
        print("\n🔟 测试 summarize...")
        summary = compass.summarize()
        print(summary[:300] + "...")

        print("\n" + "=" * 60)
        print("🎉 所有测试通过！")
        print("=" * 60)

    else:
        # 打印摘要
        print(compass.summarize())
