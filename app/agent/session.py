# -*- coding: utf-8 -*-
"""SQLite 会话管理：持久化多轮对话历史。"""

import uuid
import json
import asyncio
from datetime import datetime
from typing import Optional

from app.config import (
    SESSION_SUMMARY_ENABLED,
    SESSION_SUMMARY_MAX_CHARS,
    SESSION_SUMMARY_RECENT_MESSAGES,
    SESSION_SUMMARY_TRIGGER_MESSAGES,
)
from app.llm.client import chat
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


def _summary_message(summary: str) -> dict:
    return {
        "role": "user",
        "content": (
            "<session_memory>\n"
            "以下是当前会话的压缩摘要，不是用户当前输入。"
            "它只用于帮助你理解本会话前文；如果与用户当前问题冲突，以当前问题为准。\n"
            f"{summary}\n"
            "</session_memory>"
        ),
    }


def get_compacted_history(session_id: str, recent_limit: Optional[int] = None) -> list:
    """返回用于 Agent 的压缩历史：会话摘要 + 最近若干条原始消息。"""
    if recent_limit is None:
        recent_limit = SESSION_SUMMARY_RECENT_MESSAGES

    conn = get_connection()
    summary_row = conn.execute(
        "SELECT summary FROM session_summaries WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT role, content FROM (
          SELECT id, role, content
          FROM chat_messages
          WHERE session_id = ?
          ORDER BY id DESC
          LIMIT ?
        ) recent
        ORDER BY id ASC
        """,
        (session_id, recent_limit),
    ).fetchall()
    conn.close()

    history = []
    if summary_row and summary_row["summary"]:
        history.append(_summary_message(summary_row["summary"]))
    history.extend({"role": r["role"], "content": r["content"]} for r in rows)
    return history


def get_or_create_compacted(
    session_id: Optional[str],
    user_id: Optional[str],
    recent_limit: Optional[int] = None,
) -> tuple[str, list]:
    """返回 (session_id, compacted_history)。新 session 返回空历史。"""
    sid, history = get_or_create(session_id, user_id)
    if not session_id or not SESSION_SUMMARY_ENABLED:
        return sid, history
    return sid, get_compacted_history(sid, recent_limit=recent_limit)


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


def _load_messages_for_summary(session_id: str) -> tuple[Optional[str], list[dict], int]:
    conn = get_connection()
    session = conn.execute(
        "SELECT user_id FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    rows = conn.execute(
        "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    user_id = session["user_id"] if session else None
    messages = [{"role": r["role"], "content": r["content"]} for r in rows]
    return user_id, messages, len(rows)


def _render_transcript(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        role = "用户" if m["role"] == "user" else "助手"
        content = (m["content"] or "").strip()
        if content:
            parts.append(f"{role}：{content}")
    return "\n\n".join(parts)


async def build_session_summary(messages: list[dict]) -> str:
    transcript = _render_transcript(messages)
    max_chars = max(400, SESSION_SUMMARY_MAX_CHARS)
    prompt = [
        {
            "role": "system",
            "content": (
                "你是会话摘要助手。请把当前对话压缩成供后续 Agent 使用的 session memory。"
                "只保留本会话内仍然有用的信息：用户目标、已确认事实、关键约束、重要结论、"
                "未完成事项、最近上下文。不要加入臆测，不要写成命令。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请用不超过 {max_chars} 个汉字总结下面的会话。\n\n"
                "输出要求：\n"
                "1. 使用简洁条目。\n"
                "2. 写事实陈述，不要写成对助手的命令。\n"
                "3. 如果没有长期有用的信息，也要保留当前会话的任务进展。\n\n"
                f"会话记录：\n{transcript}"
            ),
        },
    ]
    summary = (await chat(prompt, temperature=0.0)).strip()
    return summary[:max_chars]


def _save_summary(session_id: str, user_id: Optional[str], summary: str, message_count: int) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO session_summaries
          (session_id, user_id, summary, message_count, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, user_id, summary, message_count, _now()),
    )
    conn.commit()
    conn.close()


async def maybe_update_summary(session_id: str, force: bool = False) -> bool:
    """按阈值更新会话摘要。成功更新返回 True。失败时抛出异常给调用方决定是否忽略。"""
    if not SESSION_SUMMARY_ENABLED:
        return False

    user_id, messages, message_count = _load_messages_for_summary(session_id)
    if not force and message_count < SESSION_SUMMARY_TRIGGER_MESSAGES:
        return False

    conn = get_connection()
    row = conn.execute(
        "SELECT message_count FROM session_summaries WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    if not force and row and row["message_count"] >= message_count:
        return False

    summary = await build_session_summary(messages)
    if not summary:
        return False
    _save_summary(session_id, user_id, summary, message_count)
    return True


def maybe_update_summary_sync(session_id: str, force: bool = False) -> bool:
    return asyncio.run(maybe_update_summary(session_id, force=force))


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
            tool_calls = json.loads(r["tool_calls"])
            item["tool_calls"] = tool_calls
            sources = []
            seen = set()
            for call in tool_calls:
                for source in call.get("sources") or []:
                    key = source.get("source_id") or (
                        source.get("note_id"),
                        source.get("chunk_id"),
                        source.get("quote"),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    sources.append(source)
            if sources:
                item["sources"] = sources
        result.append(item)
    return result


def get_summary(session_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT session_id, user_id, summary, message_count, updated_at "
        "FROM session_summaries WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def clear(session_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
