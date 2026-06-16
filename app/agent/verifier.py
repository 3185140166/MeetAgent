# -*- coding: utf-8 -*-
"""Lightweight answer verification for trusted meeting QA."""

from __future__ import annotations

import json
import re
from typing import Any

from app.config import AGENT_VERIFIER_ENABLED
from app.llm.client import chat, chat_json


INTERNAL_ID_PATTERN = re.compile(
    r"\b(?:note_id|chunk_id|user_id)\b|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _empty_verification(passed: bool = True, skipped: bool = False) -> dict:
    return {
        "passed": passed,
        "unsupported_claims": [],
        "missing_points": [],
        "leaked_internal_ids": [],
        "need_more_search": False,
        "rewrite_instruction": "",
        "skipped": skipped,
    }


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _normalize_verification(value: Any, answer: str) -> dict:
    data = value if isinstance(value, dict) else {}
    leaked = _safe_list(data.get("leaked_internal_ids"))
    leaked.extend(sorted(set(INTERNAL_ID_PATTERN.findall(answer or ""))))

    verification = {
        "passed": bool(data.get("passed", True)),
        "unsupported_claims": _safe_list(data.get("unsupported_claims")),
        "missing_points": _safe_list(data.get("missing_points")),
        "leaked_internal_ids": leaked,
        "need_more_search": bool(data.get("need_more_search", False)),
        "rewrite_instruction": str(data.get("rewrite_instruction") or ""),
        "skipped": False,
    }
    if verification["leaked_internal_ids"]:
        verification["passed"] = False
        if not verification["rewrite_instruction"]:
            verification["rewrite_instruction"] = "Remove internal ids and keep only user-facing meeting facts."
    return verification


def _source_digest(sources: list[dict], limit: int = 12) -> str:
    rows = []
    for source in sources[:limit]:
        rows.append({
            "source_id": source.get("source_id", ""),
            "meeting_title": source.get("meeting_title", ""),
            "create_time": source.get("create_time", ""),
            "speaker": source.get("speaker", ""),
            "quote": source.get("quote", ""),
        })
    return json.dumps(rows, ensure_ascii=False)


def _tool_digest(tool_logs: list[dict], limit: int = 10) -> str:
    rows = []
    for item in tool_logs[:limit]:
        rows.append({
            "tool": item.get("tool", ""),
            "arguments": item.get("arguments", {}),
            "failed": item.get("failed", False),
            "result_preview": item.get("result_preview", ""),
        })
    return json.dumps(rows, ensure_ascii=False)


async def verify_answer(
    question: str,
    answer: str,
    sources: list[dict],
    tool_logs: list[dict],
) -> dict:
    """Return a stable verification dict. Verifier failures do not fail QA."""
    if not AGENT_VERIFIER_ENABLED:
        return _empty_verification(skipped=True)

    heuristic = _normalize_verification({}, answer)
    if not answer.strip():
        heuristic["passed"] = False
        heuristic["unsupported_claims"] = ["Answer is empty."]
        heuristic["rewrite_instruction"] = "Answer the user directly, or say the evidence is insufficient."
        return heuristic

    try:
        result = await chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a strict QA verifier for a meeting assistant. "
                        "Check whether the answer is supported by the provided sources and tool logs. "
                        "Do not require every sentence to cite a source, but flag concrete unsupported facts. "
                        "Internal ids such as note_id, chunk_id, user_id, UUID-like ids must not appear in the final answer. "
                        "Return only valid JSON with keys: passed, unsupported_claims, missing_points, "
                        "leaked_internal_ids, need_more_search, rewrite_instruction."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\n"
                        f"Answer:\n{answer}\n\n"
                        f"Sources JSON:\n{_source_digest(sources)}\n\n"
                        f"Tool logs JSON:\n{_tool_digest(tool_logs)}"
                    ),
                },
            ],
            temperature=0.0,
        )
        return _normalize_verification(result, answer)
    except Exception as exc:
        heuristic["passed"] = not heuristic["leaked_internal_ids"]
        heuristic["error"] = str(exc)
        return heuristic


async def rewrite_answer(
    question: str,
    draft_answer: str,
    verification: dict,
    sources: list[dict],
) -> str:
    """Rewrite a failed draft using only user-facing evidence."""
    if not AGENT_VERIFIER_ENABLED:
        return draft_answer

    try:
        rewritten = await chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite the assistant answer for a meeting QA product. "
                        "Use only the provided sources. Remove unsupported claims and all internal ids. "
                        "If evidence is insufficient, say so clearly. Keep the answer concise and helpful."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\n"
                        f"Draft answer:\n{draft_answer}\n\n"
                        f"Verification JSON:\n{json.dumps(verification, ensure_ascii=False)}\n\n"
                        f"Sources JSON:\n{_source_digest(sources)}"
                    ),
                },
            ],
            temperature=0.0,
        )
        rewritten = rewritten.strip()
        return rewritten or draft_answer
    except Exception:
        return draft_answer
