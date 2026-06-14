# -*- coding: utf-8 -*-
"""Stop-hook long-term memory extraction."""

from typing import Optional

from app.config import (
    MEMORY_EXTRACTION_ENABLED,
    MEMORY_EXTRACTION_MAX_MEMORIES,
    MEMORY_EXTRACTION_MIN_CONFIDENCE,
)
from app.llm.client import chat_json
from app.memory.prompts import build_memory_extraction_messages, build_memory_update_messages
from app.memory.store import add_memory, find_similar_memories, mark_deprecated, update_memory


def should_extract_memory(question: str, answer: str, tool_calls_log: list) -> bool:
    """轻量规则：明显无长期价值的问题先跳过，减少 LLM 调用。"""
    text = f"{question}\n{answer}".lower()
    triggers = (
        "记住",
        "以后",
        "偏好",
        "我喜欢",
        "我不喜欢",
        "这个项目",
        "项目使用",
        "约定",
        "长期",
        "不要忘",
        "remember",
        "preference",
    )
    if any(t in text for t in triggers):
        return True
    if tool_calls_log:
        return any(call.get("tool") in ("get_topic_history", "generate_weekly_report") for call in tool_calls_log)
    return False


def _clamp_confidence(value) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except Exception:
        return 0.0


async def _decide_memory_update(candidate: dict, existing: list[dict]) -> dict:
    if not existing:
        return {
            "action": "ADD",
            "target_memory_id": "",
            "content": candidate.get("content", ""),
            "reason": "无相似旧记忆",
        }
    data = await chat_json(build_memory_update_messages(candidate, existing), temperature=0.0)
    action = (data.get("action") or "ADD").strip().upper()
    if action not in {"ADD", "UPDATE", "REPLACE", "IGNORE"}:
        action = "ADD"
    return {
        "action": action,
        "target_memory_id": data.get("target_memory_id") or "",
        "content": data.get("content") or candidate.get("content", ""),
        "reason": data.get("reason") or "",
    }


async def store_memory_candidate(
    *,
    candidate: dict,
    session_id: str,
    user_id: Optional[str],
    question: str,
    answer: str,
    tool_calls_log: list,
) -> Optional[dict]:
    """Store one candidate using ADD/UPDATE/REPLACE/IGNORE semantics."""
    confidence = _clamp_confidence(candidate.get("confidence", 0))
    content = (candidate.get("content") or "").strip()
    if confidence < MEMORY_EXTRACTION_MIN_CONFIDENCE or not content:
        return None

    scope = candidate.get("scope") or "user"
    memory_type = candidate.get("memory_type") or "fact"
    subject = candidate.get("subject") or ""
    similar = find_similar_memories(
        user_id=user_id,
        subject=subject,
        content=content,
        scope=scope,
        memory_type=memory_type,
        limit=5,
    )
    decision = await _decide_memory_update(candidate, similar)
    action = decision["action"]
    final_content = (decision.get("content") or content).strip()

    evidence = {
        "question": question,
        "answer": answer,
        "tool_calls": tool_calls_log,
        "update_decision": decision,
    }

    if action == "IGNORE":
        return None

    if action == "UPDATE" and decision.get("target_memory_id"):
        return update_memory(
            decision["target_memory_id"],
            content=final_content,
            subject=subject,
            trust_score=max(confidence, 0.7),
            evidence=evidence,
            source_type="chat",
            source_id=session_id,
            expires_at=candidate.get("expires_at") or "",
        )

    if action == "REPLACE" and decision.get("target_memory_id"):
        mark_deprecated(decision["target_memory_id"])

    return add_memory(
        user_id=user_id,
        scope=scope,
        memory_type=memory_type,
        subject=subject,
        content=final_content,
        trust_score=confidence,
        source_type="chat",
        source_id=session_id,
        evidence=evidence,
        expires_at=candidate.get("expires_at") or "",
    )


async def extract_and_store_memories(
    *,
    session_id: str,
    user_id: Optional[str],
    question: str,
    answer: str,
    tool_calls_log: list,
    session_summary: str = "",
    force: bool = False,
) -> list[dict]:
    """从一轮对话抽取长期记忆并写入 memories。失败由调用方捕获。"""
    if not MEMORY_EXTRACTION_ENABLED and not force:
        return []
    if not force and not should_extract_memory(question, answer, tool_calls_log):
        return []

    messages = build_memory_extraction_messages(
        question=question,
        answer=answer,
        tool_calls_log=tool_calls_log,
        session_summary=session_summary,
    )
    data = await chat_json(messages, temperature=0.0)
    candidates = data.get("memories", []) if isinstance(data, dict) else []
    if not isinstance(candidates, list):
        return []

    saved = []
    for item in candidates[:MEMORY_EXTRACTION_MAX_MEMORIES]:
        if not isinstance(item, dict):
            continue
        memory = await store_memory_candidate(
            candidate=item,
            session_id=session_id,
            user_id=user_id,
            question=question,
            answer=answer,
            tool_calls_log=tool_calls_log,
        )
        if memory:
            saved.append(memory)
    return saved
