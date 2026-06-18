# -*- coding: utf-8 -*-
"""Long-term memory retrieval for user profile and agent reflections."""

import re
from typing import Optional

from app.config import (
    MEMORY_GATE_ENABLED,
    MEMORY_GATE_LOOSE_MIN_TRUST,
    MEMORY_GATE_STRICT_MIN_TRUST,
    MEMORY_PREFERENCE_TOP_K,
    MEMORY_RETRIEVAL_ENABLED,
    REFLEXION_RETRIEVAL_TOP_K,
)
from app.memory.reflexion import format_reflection_context
from app.storage.db import get_connection

_EXPLICIT_MEMORY_TRIGGERS = (
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
    "约定",
    "历史",
    "按我的偏好",
    "remember",
    "preference",
)

_STOPWORDS = {
    "这个",
    "那个",
    "什么",
    "怎么",
    "如何",
    "哪些",
    "一下",
    "一个",
    "问题",
    "这里",
    "现在",
    "就是",
    "然后",
    "可以",
    "应该",
    "进行",
    "修改",
    "会议",
    "系统",
    "用户",
    "长期",
    "记忆",
    "召回",
    "相关",
    "信息",
    "内容",
    "方式",
}


def should_retrieve_memory(question: str) -> bool:
    """Return True when the user explicitly asks for historical memory."""
    text = (question or "").lower()
    return any(trigger in text for trigger in _EXPLICIT_MEMORY_TRIGGERS)


def _trust(memory: dict) -> float:
    try:
        return float(memory.get("trust_score") or 0.0)
    except Exception:
        return 0.0


def _memory_text(memory: dict) -> str:
    return f"{memory.get('subject') or ''}\n{memory.get('content') or ''}"


def _tokens(text: str) -> set[str]:
    text = (text or "").lower()
    words = set(re.findall(r"[a-z0-9_]{2,}", text))
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    for run in chinese_runs:
        if run in _STOPWORDS:
            continue
        words.add(run)
        words.update(run[i : i + 2] for i in range(max(len(run) - 1, 0)))
    return {word for word in words if word and word not in _STOPWORDS}


def _overlap_score(question: str, memory: dict) -> float:
    q_tokens = _tokens(question)
    if not q_tokens:
        return 0.0
    m_tokens = _tokens(_memory_text(memory))
    if not m_tokens:
        return 0.0
    return len(q_tokens & m_tokens) / max(len(q_tokens), 1)


def _fetch_memory_candidates(
    *,
    user_id: Optional[str],
    memory_type: str,
    limit: int,
) -> list[dict]:
    conn = get_connection()
    try:
        params: list = [memory_type]
        user_filter = ""
        if user_id:
            user_filter = "AND user_id = ?"
            params.append(user_id)
        params.append(min(max(int(limit or 1), 1), 50))
        return [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT *
                FROM memories
                WHERE status = 'active'
                  AND memory_type = ?
                  {user_filter}
                ORDER BY trust_score DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        ]
    finally:
        conn.close()


def _dedupe_memories(rows: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for row in rows:
        memory_id = row.get("memory_id")
        if not memory_id or memory_id in seen:
            continue
        seen.add(memory_id)
        deduped.append(row)
    return deduped


def memory_gate(
    question: str,
    candidates: list[dict],
    *,
    explicit: bool,
    limit: int,
    type_hint: Optional[str] = None,
) -> list[dict]:
    """Filter reflection candidates before context injection."""
    candidates = _dedupe_memories(candidates)
    if not MEMORY_GATE_ENABLED:
        return sorted(candidates, key=_trust, reverse=True)[:limit]

    accepted: list[tuple[float, dict]] = []
    for memory in candidates:
        memory_type = type_hint or memory.get("memory_type") or ""
        trust = _trust(memory)
        overlap = _overlap_score(question, memory)

        if memory_type == "preference":
            keep = trust >= MEMORY_GATE_LOOSE_MIN_TRUST
        elif memory_type == "reflection":
            min_trust = MEMORY_GATE_LOOSE_MIN_TRUST if explicit else MEMORY_GATE_STRICT_MIN_TRUST
            keep = trust >= min_trust and (explicit or overlap >= 0.03)
        else:
            keep = False

        if keep:
            accepted.append((trust + min(overlap, 0.5), memory))

    accepted.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in accepted[:limit]]


def retrieve_preference_memories(*, user_id: Optional[str], limit: Optional[int] = None) -> list[dict]:
    if not MEMORY_RETRIEVAL_ENABLED:
        return []
    rows = _fetch_memory_candidates(
        user_id=user_id,
        memory_type="preference",
        limit=limit or MEMORY_PREFERENCE_TOP_K,
    )
    return memory_gate("", rows, explicit=True, limit=limit or 1, type_hint="preference")


def retrieve_reflection_memories(
    *,
    question: str,
    user_id: Optional[str],
    limit: Optional[int] = None,
) -> list[dict]:
    if not MEMORY_RETRIEVAL_ENABLED:
        return []
    rows = _fetch_memory_candidates(
        user_id=user_id,
        memory_type="reflection",
        limit=limit or REFLEXION_RETRIEVAL_TOP_K,
    )
    return memory_gate(
        question,
        rows,
        explicit=should_retrieve_memory(question),
        limit=limit or REFLEXION_RETRIEVAL_TOP_K,
        type_hint="reflection",
    )


def retrieve_memories(
    *,
    question: str,
    user_id: Optional[str],
    force: bool = False,
    limit: Optional[int] = None,
) -> list[dict]:
    """Backward-compatible retrieval entry point."""
    if not force and not MEMORY_RETRIEVAL_ENABLED:
        return []
    rows = [
        *retrieve_preference_memories(user_id=user_id, limit=1),
        *retrieve_reflection_memories(question=question, user_id=user_id, limit=limit),
    ]
    return _dedupe_memories(rows)


def format_user_profile(preferences: list[dict]) -> str:
    if not preferences:
        return ""
    profile = preferences[0]
    return (
        "<user_profile>\n"
        "以下是稳定用户画像，不是当前用户输入。仅在有助于回答风格、交互方式或任务推进时参考；"
        "如与当前指令冲突，以当前指令为准。\n"
        f"{profile.get('content')}\n"
        "</user_profile>"
    )


def format_memory_context(memories: list[dict]) -> str:
    """Backward-compatible formatter."""
    preferences = [m for m in memories if m.get("memory_type") == "preference"]
    reflections = [m for m in memories if m.get("memory_type") == "reflection"]
    parts = [format_user_profile(preferences), format_reflection_context(reflections)]
    return "\n\n".join(part for part in parts if part)


def build_memory_message(question: str, user_id: Optional[str]) -> Optional[dict]:
    if not MEMORY_RETRIEVAL_ENABLED:
        return None

    preferences = retrieve_preference_memories(user_id=user_id, limit=1)
    reflections = retrieve_reflection_memories(question=question, user_id=user_id)

    parts = [
        part
        for part in (
            format_user_profile(preferences),
            format_reflection_context(reflections),
        )
        if part
    ]
    if not parts:
        return None
    return {"role": "user", "content": "\n\n".join(parts)}
