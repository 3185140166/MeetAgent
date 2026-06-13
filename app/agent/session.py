# -*- coding: utf-8 -*-
"""SQLite 会话管理：持久化多轮对话历史。"""

import uuid
import json
from datetime import datetime
from typing import Optional

from app.storage.db import get_connection


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def get_or_create(session_id: Optional[str], user_id: Optional[str]) -> tuple[str, list]:
    """返回 (session_id, history)。history 是 [{role, content}, ...] 列表。"""
    conn = get_connection()

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


def list_sessions(limit: int = 50, offset: int = 0, user_id: Optional[str] = None) -> list:
    conn = get_connection()
    params = []
    where = ""
    if user_id:
        where = "WHERE s.user_id = ?"
        params.append(user_id)
    params.extend([limit, offset])

    rows = conn.execute(
        f"""
        SELECT
          s.session_id,
          s.user_id,
          s.created_at,
          s.updated_at,
          COUNT(m.id) AS message_count,
          (
            SELECT cm.content
            FROM chat_messages cm
            WHERE cm.session_id = s.session_id AND cm.role = 'user'
            ORDER BY cm.id DESC
            LIMIT 1
          ) AS last_user_message
        FROM chat_sessions s
        LEFT JOIN chat_messages m ON m.session_id = s.session_id
        {where}
        GROUP BY s.session_id
        ORDER BY s.updated_at DESC
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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
