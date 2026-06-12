# -*- coding: utf-8 -*-
"""SQLite 会话管理：持久化多轮对话历史，30 分钟无操作自动过期。"""

import uuid
import json
from datetime import datetime, timedelta
from typing import Optional

from app.storage.db import get_connection

_TTL = timedelta(minutes=30)


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _cutoff() -> str:
    return (datetime.utcnow() - _TTL).strftime("%Y-%m-%d %H:%M:%S")


def get_or_create(session_id: Optional[str], user_id: Optional[str]) -> tuple[str, list]:
    """返回 (session_id, history)。history 是 [{role, content}, ...] 列表。"""
    conn = get_connection()

    # 清理过期 session
    cut = _cutoff()
    conn.execute(
        "DELETE FROM chat_messages WHERE session_id IN "
        "(SELECT session_id FROM chat_sessions WHERE updated_at < ?)", (cut,)
    )
    conn.execute("DELETE FROM chat_sessions WHERE updated_at < ?", (cut,))
    conn.commit()

    if session_id:
        row = conn.execute(
            "SELECT session_id FROM chat_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row:
            msgs = conn.execute(
                "SELECT role, content FROM chat_messages "
                "WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                (_now(), session_id),
            )
            conn.commit()
            conn.close()
            return session_id, [{"role": r["role"], "content": r["content"]} for r in msgs]

    # 新建 session
    new_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO chat_sessions (session_id, user_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (new_id, user_id, _now(), _now()),
    )
    conn.commit()
    conn.close()
    return new_id, []


def append_turn(
    session_id: str,
    question: str,
    answer: str,
    tool_calls_log: list,
):
    """追加一轮对话（用户问 + 助手答）到数据库。"""
    conn = get_connection()
    now = _now()
    tool_calls_json = json.dumps(tool_calls_log, ensure_ascii=False) if tool_calls_log else None

    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
        (session_id, question, now),
    )
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, tool_calls, created_at) "
        "VALUES (?, 'assistant', ?, ?, ?)",
        (session_id, answer, tool_calls_json, now),
    )
    conn.execute(
        "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
        (now, session_id),
    )
    conn.commit()
    conn.close()


def get_history(session_id: str) -> list:
    """返回某 session 的完整消息列表（含 tool_calls）。"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT role, content, tool_calls, created_at FROM chat_messages "
        "WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        item = {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
        if r["tool_calls"]:
            item["tool_calls"] = json.loads(r["tool_calls"])
        result.append(item)
    return result


def clear(session_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
