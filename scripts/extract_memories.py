# -*- coding: utf-8 -*-
"""从指定会话最后一轮对话中抽取 Long-term Memory。"""

import argparse
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.agent import session as sess
from app.memory.extractor import extract_and_store_memories
from app.storage.db import get_connection, init_db


def _load_last_turn(session_id: str) -> tuple[str | None, str, str, list]:
    conn = get_connection()
    session = conn.execute(
        "SELECT user_id FROM chat_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    rows = conn.execute(
        """
        SELECT role, content, tool_calls
        FROM chat_messages
        WHERE session_id = ?
        ORDER BY id DESC
        LIMIT 2
        """,
        (session_id,),
    ).fetchall()
    conn.close()

    if len(rows) < 2:
        raise ValueError("该 session 至少需要一轮 user + assistant 对话")

    assistant = rows[0]
    user = rows[1]
    if assistant["role"] != "assistant" or user["role"] != "user":
        raise ValueError("最近两条消息不是完整的一轮 user + assistant")

    import json
    tool_calls = json.loads(assistant["tool_calls"]) if assistant["tool_calls"] else []
    user_id = session["user_id"] if session else None
    return user_id, user["content"], assistant["content"], tool_calls


async def main(session_id: str, force: bool):
    init_db()
    user_id, question, answer, tool_calls = _load_last_turn(session_id)
    summary = sess.get_summary(session_id) or {}
    memories = await extract_and_store_memories(
        session_id=session_id,
        user_id=user_id,
        question=question,
        answer=answer,
        tool_calls_log=tool_calls,
        session_summary=summary.get("summary", ""),
        force=force,
    )
    print(f"抽取完成：{len(memories)} 条")
    for memory in memories:
        print(f"- {memory['memory_id']} [{memory['scope']}/{memory['memory_type']}] {memory.get('subject') or '-'}")
        print(f"  {memory['content']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从指定会话最后一轮对话抽取长期记忆")
    parser.add_argument("session_id", help="会话 ID")
    parser.add_argument("--force", action="store_true", help="忽略开关和轻量规则，强制调用 LLM 抽取")
    args = parser.parse_args()
    asyncio.run(main(args.session_id, args.force))
