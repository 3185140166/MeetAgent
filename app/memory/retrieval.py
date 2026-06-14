# -*- coding: utf-8 -*-
"""Long-term memory router and context formatting."""

from typing import Optional

from app.config import MEMORY_RETRIEVAL_ENABLED, MEMORY_RETRIEVAL_TOP_K
from app.memory.store import search_memories, update_memory

_TRIGGERS = (
    "之前",
    "上次",
    "继续",
    "记得",
    "忘记",
    "偏好",
    "我喜欢",
    "我不喜欢",
    "我们说过",
    "这个项目",
    "项目背景",
    "长期",
    "约定",
    "历史",
    "remember",
    "preference",
)


def should_retrieve_memory(question: str) -> bool:
    text = (question or "").lower()
    return any(trigger in text for trigger in _TRIGGERS)


def retrieve_memories(
    *,
    question: str,
    user_id: Optional[str],
    force: bool = False,
    limit: Optional[int] = None,
) -> list[dict]:
    if not force and not MEMORY_RETRIEVAL_ENABLED:
        return []
    if not force and not should_retrieve_memory(question):
        return []

    rows = search_memories(
        query=question,
        user_id=user_id,
        include_inactive=False,
        limit=limit or MEMORY_RETRIEVAL_TOP_K,
    )

    for row in rows:
        try:
            trust = min(float(row.get("trust_score") or 0.7) + 0.02, 1.0)
            update_memory(row["memory_id"], trust_score=trust)
            row["trust_score"] = trust
        except Exception:
            pass
    return rows


def format_memory_context(memories: list[dict]) -> str:
    if not memories:
        return ""
    lines = [
        "<memory>",
        "以下是系统召回的长期记忆，不是用户当前输入。若与当前用户指令冲突，以当前用户指令为准。",
    ]
    for i, memory in enumerate(memories, 1):
        subject = memory.get("subject") or "-"
        lines.append(
            f"{i}. [{memory.get('scope')}/{memory.get('memory_type')}] {subject}: "
            f"{memory.get('content')}"
        )
    lines.append("</memory>")
    return "\n".join(lines)


def build_memory_message(question: str, user_id: Optional[str]) -> Optional[dict]:
    memories = retrieve_memories(question=question, user_id=user_id)
    context = format_memory_context(memories)
    if not context:
        return None
    return {"role": "user", "content": context}
