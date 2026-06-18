# -*- coding: utf-8 -*-
"""User-feedback driven reflection memory."""

import json
from typing import Optional

from app.config import REFLEXION_ENABLED, REFLEXION_MAX_REFLECTIONS, REFLEXION_MIN_CONFIDENCE
from app.llm.client import chat_json
from app.memory.store import add_memory, find_similar_memories, update_memory
from app.storage.db import get_connection

_NEGATIVE_FEEDBACK_MARKERS = (
    "不对",
    "错了",
    "不是",
    "不准确",
    "有问题",
    "理解错",
    "不是这个意思",
    "重复",
    "没看到",
    "没有引用",
    "来源不对",
    "引用不对",
    "应该是",
    "重新",
)

_POSITIVE_FEEDBACK_MARKERS = (
    "这样可以",
    "我觉得可以",
    "可以这样",
    "就按这个",
    "这个方案可以",
    "这个可以",
    "对的",
    "可以按照",
)


FEEDBACK_REFLECTION_SYSTEM_PROMPT = """你是 MeetAgent 的用户反馈反思模块。
你的任务不是回答用户问题，而是根据用户对上一轮结果的纠错、反驳、确认或认可，提炼下次可复用的 Agent 行为经验。

只保存可以泛化到未来相似任务的经验。不要保存会议事实、一次性答案、用户隐私、完整聊天记录。

如果用户是在纠错，优先总结：
- 上一轮哪里没有满足用户预期；
- 下次如何选择工具、检索、组织回答或展示来源；
- 如何避免重复错误。

如果用户是在认可，优先总结：
- 哪种处理方式被用户认可；
- 下次相似任务可以复用的回答结构、工具策略或交互方式。

只输出 JSON：
{
  "should_store": true,
  "reflections": [
    {
      "subject": "user_feedback:correction",
      "content": "当用户指出引用来源重复时，应先按 chunk_id/note_id 去重，只展示少量代表性来源，并提供展开全部入口。",
      "confidence": 0.82,
      "scope": "project",
      "memory_type": "reflection"
    }
  ]
}

subject 只能使用这些前缀：
- user_feedback:correction
- user_feedback:missing_expectation
- success_pattern:meeting_qa
- success_pattern:memory_design
- success_pattern:debugging
- answer:structure
- answer:citation
- retrieval:strategy
- tool_use:strategy
"""


def feedback_kind(text: str) -> Optional[str]:
    text = (text or "").lower()
    if any(marker in text for marker in _NEGATIVE_FEEDBACK_MARKERS):
        return "negative"
    if any(marker in text for marker in _POSITIVE_FEEDBACK_MARKERS):
        return "positive"
    return None


def _load_previous_turn(session_id: str) -> Optional[dict]:
    """Load the assistant turn immediately before the latest saved turn."""
    conn = get_connection()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, role, content, tool_calls, created_at
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT 4
                """,
                (session_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    # After append_turn(), latest rows are current assistant, current user,
    # previous assistant, previous user.
    previous_assistant = None
    previous_user = None
    for row in rows[2:]:
        if row.get("role") == "assistant" and previous_assistant is None:
            previous_assistant = row
        elif row.get("role") == "user" and previous_user is None:
            previous_user = row
    if not previous_assistant and not previous_user:
        return None

    tool_calls = []
    if previous_assistant and previous_assistant.get("tool_calls"):
        try:
            tool_calls = json.loads(previous_assistant["tool_calls"])
        except Exception:
            tool_calls = []

    verification = None
    for call in tool_calls:
        if isinstance(call, dict) and call.get("tool") == "answer_verifier":
            verification = call.get("verification")

    return {
        "previous_question": (previous_user or {}).get("content") or "",
        "previous_answer": (previous_assistant or {}).get("content") or "",
        "previous_tool_calls": tool_calls,
        "previous_verification": verification or {},
    }


def _clamp_confidence(value) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except Exception:
        return 0.0


async def _generate_feedback_reflections(
    *,
    feedback_type: str,
    question: str,
    answer: str,
    tool_calls_log: list[dict],
    sources: list[dict],
    verification: Optional[dict],
    previous_turn: Optional[dict],
) -> list[dict]:
    messages = [
        {"role": "system", "content": FEEDBACK_REFLECTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "feedback_type": feedback_type,
                    "current_user_message": question,
                    "current_answer": answer,
                    "current_tool_calls": tool_calls_log or [],
                    "current_sources": sources or [],
                    "current_verification": verification or {},
                    "previous_turn": previous_turn or {},
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
                "subject": item.get("subject") or (
                    "user_feedback:correction" if feedback_type == "negative" else "success_pattern:meeting_qa"
                ),
                "content": content,
                "confidence": confidence,
            }
        )
    return cleaned


async def store_feedback_reflections(
    *,
    session_id: str,
    user_id: Optional[str],
    question: str,
    answer: str,
    tool_calls_log: list[dict],
    sources: list[dict],
    verification: Optional[dict],
) -> list[dict]:
    if not REFLEXION_ENABLED:
        return []

    kind = feedback_kind(question)
    if not kind:
        return []

    previous_turn = _load_previous_turn(session_id)
    candidates = await _generate_feedback_reflections(
        feedback_type=kind,
        question=question,
        answer=answer,
        tool_calls_log=tool_calls_log,
        sources=sources,
        verification=verification,
        previous_turn=previous_turn,
    )

    saved = []
    evidence = {
        "feedback_type": kind,
        "question": question,
        "answer": answer,
        "tool_calls_log": tool_calls_log or [],
        "sources": sources or [],
        "verification": verification or {},
        "previous_turn": previous_turn or {},
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
                max(float(old.get("trust_score") or 0.7), candidate["confidence"]) + 0.04,
                1.0,
            )
            updated = update_memory(
                old["memory_id"],
                trust_score=new_score,
                evidence=evidence,
                source_type="user_feedback_reflection",
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
                source_type="user_feedback_reflection",
                source_id=session_id,
                evidence=evidence,
            )
        )
    return saved
