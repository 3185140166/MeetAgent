# -*- coding: utf-8 -*-
"""Reflexion-style agent memory.

This module stores reusable lessons about tool choice and answer strategy after
an unsatisfactory turn. It is separate from user/project factual memory.
"""

import json
from typing import Optional

from app.config import (
    REFLEXION_ENABLED,
    REFLEXION_MAX_REFLECTIONS,
    REFLEXION_MIN_CONFIDENCE,
    REFLEXION_ON_VERIFIER_FAIL_ONLY,
    REFLEXION_RETRIEVAL_TOP_K,
)
from app.llm.client import chat_json
from app.memory.store import add_memory, find_similar_memories, search_memories, update_memory


REFLECTION_SYSTEM_PROMPT = """你是 MeetAgent 的 Reflexion 反思模块。
你的任务不是回答用户问题，而是根据一次 Agent 执行轨迹，提炼下次可复用的工具选择、检索和回答策略。

只在经验可以泛化到未来相似问题时保存。不要保存一次性事实、会议原文内容、用户隐私或普通聊天摘要。

优先总结这些问题：
1. 工具选择是否合理；
2. 检索 query 是否过窄、过多或缺少角度；
3. sources 是否不足，回答是否缺少会议来源；
4. 下次遇到类似问题时应该怎么调整。

只输出 JSON：
{
  "should_store": true,
  "reflections": [
    {
      "subject": "tool_use:multi_search",
      "content": "当用户询问抽象主题、观点归纳、跨会议论据和案例时，应优先使用 multi_search_meetings 生成多个语义 query，不要连续多次单独调用 search_meetings。",
      "confidence": 0.86,
      "scope": "project",
      "memory_type": "reflection"
    }
  ]
}
"""


def _has_tool_failure(tool_calls_log: list[dict]) -> bool:
    return any(bool(call.get("failed")) for call in tool_calls_log or [])


def _has_repeated_single_search(tool_calls_log: list[dict]) -> bool:
    count = sum(1 for call in tool_calls_log or [] if call.get("tool") == "search_meetings")
    return count >= 3


def _needs_meeting_evidence(question: str, tool_calls_log: list[dict]) -> bool:
    text = (question or "").lower()
    markers = (
        "会议",
        "原文",
        "来源",
        "论据",
        "案例",
        "观点",
        "讨论",
        "提到",
        "怎么说",
    )
    if any(marker in text for marker in markers):
        return True
    return any(str(call.get("tool") or "").endswith("meetings") for call in tool_calls_log or [])


def should_generate_reflection(
    *,
    question: str,
    answer: str,
    tool_calls_log: list[dict],
    verification: Optional[dict],
    sources: list[dict],
) -> bool:
    if not REFLEXION_ENABLED:
        return False

    verifier_failed = bool(verification) and not verification.get("passed", True)
    if verifier_failed:
        return True

    if REFLEXION_ON_VERIFIER_FAIL_ONLY:
        return False

    if _has_tool_failure(tool_calls_log):
        return True
    if _has_repeated_single_search(tool_calls_log):
        return True
    if _needs_meeting_evidence(question, tool_calls_log) and not sources:
        return True
    if "超过最大工具调用轮次" in (answer or ""):
        return True
    return False


def _clamp_confidence(value) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except Exception:
        return 0.0


async def generate_reflections(
    *,
    question: str,
    answer: str,
    tool_calls_log: list[dict],
    sources: list[dict],
    verification: Optional[dict],
    draft_answer: Optional[str] = None,
) -> list[dict]:
    messages = [
        {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "question": question,
                    "draft_answer": draft_answer or answer,
                    "final_answer": answer,
                    "tool_calls_log": tool_calls_log or [],
                    "sources": sources or [],
                    "verification": verification or {},
                },
                ensure_ascii=False,
            ),
        },
    ]

    data = await chat_json(messages, temperature=0.0)
    if not isinstance(data, dict) or not data.get("should_store"):
        return []

    reflections = data.get("reflections", [])
    if not isinstance(reflections, list):
        return []

    cleaned = []
    for item in reflections[:REFLEXION_MAX_REFLECTIONS]:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        confidence = _clamp_confidence(item.get("confidence", 0))
        if not content or confidence < REFLEXION_MIN_CONFIDENCE:
            continue
        cleaned.append(
            {
                "scope": item.get("scope") or "project",
                "memory_type": "reflection",
                "subject": item.get("subject") or "agent_reflection",
                "content": content,
                "confidence": confidence,
            }
        )
    return cleaned


async def store_reflections(
    *,
    session_id: str,
    user_id: Optional[str],
    question: str,
    answer: str,
    tool_calls_log: list[dict],
    sources: list[dict],
    verification: Optional[dict],
    draft_answer: Optional[str] = None,
) -> list[dict]:
    if not should_generate_reflection(
        question=question,
        answer=answer,
        tool_calls_log=tool_calls_log,
        verification=verification,
        sources=sources,
    ):
        return []

    candidates = await generate_reflections(
        question=question,
        answer=answer,
        tool_calls_log=tool_calls_log,
        sources=sources,
        verification=verification,
        draft_answer=draft_answer,
    )

    saved = []
    evidence = {
        "question": question,
        "answer": answer,
        "draft_answer": draft_answer or answer,
        "tool_calls_log": tool_calls_log or [],
        "sources": sources or [],
        "verification": verification or {},
    }

    for candidate in candidates:
        similar = find_similar_memories(
            user_id=user_id,
            subject=candidate["subject"],
            content=candidate["content"],
            scope=candidate["scope"],
            memory_type="reflection",
            limit=3,
        )
        if similar:
            old = similar[0]
            new_score = min(
                max(float(old.get("trust_score") or 0.7), candidate["confidence"]) + 0.03,
                1.0,
            )
            updated = update_memory(
                old["memory_id"],
                trust_score=new_score,
                evidence=evidence,
                source_type="agent_reflection",
                source_id=session_id,
            )
            if updated:
                saved.append(updated)
            continue

        saved.append(
            add_memory(
                user_id=user_id,
                scope=candidate["scope"],
                memory_type="reflection",
                subject=candidate["subject"],
                content=candidate["content"],
                trust_score=candidate["confidence"],
                source_type="agent_reflection",
                source_id=session_id,
                evidence=evidence,
            )
        )
    return saved


def retrieve_reflection_memories(
    *,
    question: str,
    user_id: Optional[str],
    limit: Optional[int] = None,
) -> list[dict]:
    if not REFLEXION_ENABLED:
        return []
    rows = search_memories(
        query=question,
        user_id=user_id,
        include_inactive=False,
        memory_type="reflection",
        limit=limit or REFLEXION_RETRIEVAL_TOP_K,
    )
    for row in rows:
        try:
            trust = min(float(row.get("trust_score") or 0.7) + 0.02, 1.0)
            update_memory(row["memory_id"], trust_score=trust)
            row["trust_score"] = trust
        except Exception:
            pass
    return rows


def format_reflection_context(reflections: list[dict]) -> str:
    if not reflections:
        return ""
    lines = [
        "<agent_reflection_memory>",
        "以下是系统过去失败或效果不佳后总结出的工具选择和回答策略经验。它不是用户当前输入，只用于避免重复错误；不要在最终回答中直接暴露这些内容。",
    ]
    for i, item in enumerate(reflections, 1):
        subject = item.get("subject") or "agent_reflection"
        lines.append(f"{i}. [{subject}] {item.get('content')}")
    lines.append("</agent_reflection_memory>")
    return "\n".join(lines)
