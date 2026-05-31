#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
metacognition.py — 元认知系统（自我状态感知）

用于追踪 Dawang 的当前状态、情绪、活动历史，并提供自我画像功能。
所有状态通过 SQLite 持久化，支持重启恢复（uptime 除外）。
"""

import json
import sqlite3
import time
import os
from datetime import datetime, timezone
from typing import Optional


def _get_connection(db_path: str) -> sqlite3.Connection:
    """获取 SQLite 连接，并确保 meta_state 表存在。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta_state (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


class Metacognition:
    """元认知系统 — 管理 Dawang 的自我状态感知。"""

    # ──────────────────────────────────────────
    # 初始化
    # ──────────────────────────────────────────

    def __init__(self, hormone_system, desire_manager, emotion_memory, dream_engine, db_path: str = None):
        """
        Args:
            hormone_system:   激素/情绪系统实例（需提供 get_mood_description() 方法）
            desire_manager:   欲望管理器实例
            emotion_memory:   情绪记忆实例
            dream_engine:     梦境引擎实例
            db_path:          SQLite 数据库路径（默认：mind.db 在同一目录）
        """
        self.db_path = db_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "mind.db")
        self._hormone = hormone_system
        self._desire = desire_manager
        self._emotion_memory = emotion_memory
        self._dream = dream_engine

        # 运行时状态（不持久化存储在 SQLite）
        self.current_state: str = "awake"       # awake / dreaming / sleeping
        self.cycle_count: int = 0               # 运行轮数
        self.last_activity: str = ""            # 最后一次做的什么事
        self.last_error: str = ""               # 最后一次错误
        self.uptime_minutes: float = 0.0        # 运行时长（重启后重置为 0）
        self.task_history: list = []            # 最近 10 次任务

        # 从 SQLite 恢复持久化状态（uptime 不恢复，重启即重置）
        self._restore_from_db()

    # ──────────────────────────────────────────
    # SQLite 持久化
    # ──────────────────────────────────────────

    def _save(self, key: str, value: str) -> None:
        """将 key-value 写入 meta_state 表。"""
        conn = _get_connection(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO meta_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value      = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def _load(self, key: str) -> Optional[str]:
        """从 meta_state 表读取指定 key 的值，不存在时返回 None。"""
        conn = _get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT value FROM meta_state WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def _restore_from_db(self) -> None:
        """从 SQLite 恢复持久化状态（uptime 不恢复）。"""
        state_val = self._load("current_state")
        if state_val:
            self.current_state = state_val

        cycle_val = self._load("cycle_count")
        if cycle_val:
            self.cycle_count = int(cycle_val)

        activity_val = self._load("last_activity")
        if activity_val:
            self.last_activity = activity_val

        error_val = self._load("last_error")
        if error_val:
            self.last_error = error_val

        history_val = self._load("task_history")
        if history_val:
            try:
                self.task_history = json.loads(history_val)
                # 确保不超过 10 条
                if len(self.task_history) > 10:
                    self.task_history = self.task_history[-10:]
            except (json.JSONDecodeError, TypeError):
                self.task_history = []

        # uptime 始终重置为 0，不恢复
        self.uptime_minutes = 0.0

    # ──────────────────────────────────────────
    # 公开 API
    # ──────────────────────────────────────────

    def update_state(self, state_name: str) -> None:
        """更新当前状态（awake / dreaming / sleeping），并持久化。"""
        valid_states = ("awake", "dreaming", "sleeping")
        if state_name not in valid_states:
            raise ValueError(f"无效状态：{state_name}，可选：{valid_states}")

        self.current_state = state_name
        self._save("current_state", state_name)

    def log_activity(self, description: str) -> None:
        """记录活动到 task_history，仅保留最近 10 条。"""
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {"time": timestamp, "activity": description}

        self.task_history.append(entry)
        # 只保留最近 10 条
        if len(self.task_history) > 10:
            self.task_history = self.task_history[-10:]

        self.last_activity = description
        self.cycle_count += 1

        # 持久化
        self._save("last_activity", description)
        self._save("cycle_count", str(self.cycle_count))
        self._save("task_history", json.dumps(self.task_history, ensure_ascii=False))

    def log_error(self, error_desc: str) -> None:
        """记录错误信息并持久化。"""
        self.last_error = error_desc
        self._save("last_error", error_desc)

    # ──────────────────────────────────────────
    # 自我感知接口
    # ──────────────────────────────────────────

    def what_am_i_doing(self) -> str:
        """
        返回自然语言描述当前状态。
        格式：'我正在 {state} 状态，当前主导情绪是 {emotion}，最近在忙 {last_activity}'
        """
        emotion = self._get_dominant_emotion()
        return (
            f"我正在 {self._state_label()} 状态，"
            f"当前主导情绪是 {emotion}，"
            f"最近在忙 {self.last_activity or '没什么特别的事'}"
        )

    def how_am_i_feeling(self) -> str:
        """返回情绪描述，委托给 hormone.get_mood_description()。"""
        try:
            return self._hormone.get_mood_description()
        except Exception:
            return "情绪系统暂时无法访问"

    def self_portrait(self) -> dict:
        """返回完整自我画像。"""
        return {
            "state": self.current_state,
            "cycle_count": self.cycle_count,
            "uptime_minutes": self.uptime_minutes,
            "dominant_emotion": self._get_dominant_emotion(),
            "mood_description": self.how_am_i_feeling(),
            "active_desires": self._get_active_desires(),
            "memory_count": self._get_memory_count(),
            "last_activity": self.last_activity,
            "last_error": self.last_error,
            "task_history": self.task_history,
            "personality_summary": self._get_personality_summary(),
        }

    # ──────────────────────────────────────────
    # 内部辅助方法
    # ──────────────────────────────────────────

    def _state_label(self) -> str:
        """返回当前状态的中文标签。"""
        labels = {
            "awake": "清醒",
            "dreaming": "梦境",
            "sleeping": "休眠",
        }
        return labels.get(self.current_state, self.current_state)

    def _get_dominant_emotion(self) -> str:
        """从 emotion_memory 获取当前主导情绪名称。"""
        try:
            return self._emotion_memory.get_dominant_emotion_name()
        except Exception:
            return "未知"

    def _get_active_desires(self) -> list:
        """获取活跃欲望列表（调用 desire_manager）。"""
        try:
            desires = self._desire.get_active_desires()
            # 兼容 dict 或 list 格式
            if isinstance(desires, list):
                return desires
            if isinstance(desires, dict):
                return list(desires.keys())
            return []
        except Exception:
            return []

    def _get_memory_count(self) -> int:
        """获取情绪记忆条数。"""
        try:
            return self._emotion_memory.count()
        except Exception:
            return 0

    def _get_personality_summary(self) -> str:
        """生成简要个性总结。"""
        emotion = self._get_dominant_emotion()
        state_label = self._state_label()
        activity = self.last_activity or "无"
        return (
            f"Dawang 当前处于 {state_label} 状态，"
            f"主导情绪为 {emotion}，"
            f"已运行 {self.cycle_count} 轮，"
            f"最近活动：{activity}"
        )
