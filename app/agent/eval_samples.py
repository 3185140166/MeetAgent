# -*- coding: utf-8 -*-
"""Persist Agent evaluation samples for review and training-data export."""

from __future__ import annotations

import json
import uuid
from typing import Optional

from app.storage.db import get_connection

REVIEW_PENDING = "pending"
SAMPLE_TOOL_CALL = "tool_call"
SAMPLE_ANSWER_GENERATION = "answer_generation"
SAMPLE_PREFERENCE = "preference"


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _safe_loads(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _tool_trace(tool_calls_log: list[dict]) -> list[dict]:
    return [
        {
            "tool": item.get("tool", ""),
            "arguments": item.get("arguments") or {},
            "failed": bool(item.get("failed", False)),
        }
        for item in tool_calls_log or []
        if item.get("tool") != "answer_verifier"
    ]


def _tool_results(tool_calls_log: list[dict]) -> list[dict]:
    return [
        {
            "tool": item.get("tool", ""),
            "arguments": item.get("arguments") or {},
            "failed": bool(item.get("failed", False)),
            "result_preview": item.get("result_preview", ""),
            "sources": item.get("sources") or [],
        }
        for item in tool_calls_log or []
        if item.get("tool") != "answer_verifier"
    ]


def infer_sample_type(
    tool_trace: list[dict],
    draft_answer: str,
    final_answer: str,
    verification: dict,
) -> str:
    if draft_answer and final_answer and draft_answer.strip() != final_answer.strip():
        return SAMPLE_PREFERENCE
    if tool_trace:
        return SAMPLE_TOOL_CALL
    return SAMPLE_ANSWER_GENERATION


def score_sample(
    *,
    tool_trace: list[dict],
    sources: list[dict],
    final_answer: str,
    verification: dict,
) -> float:
    score = 0.0
    if final_answer and final_answer.strip():
        score += 15
    if sources:
        score += 20
    if verification.get("passed", False):
        score += 30
    if not verification.get("unsupported_claims"):
        score += 15
    if not verification.get("missing_points"):
        score += 10
    if not verification.get("leaked_internal_ids"):
        score += 10
    if tool_trace and not any(item.get("failed") for item in tool_trace):
        score += 10
    return min(score, 100.0)


def create_eval_sample(
    *,
    session_id: Optional[str],
    user_id: Optional[str],
    question: str,
    tool_calls_log: list[dict],
    sources: list[dict],
    draft_answer: str,
    final_answer: str,
    verification: Optional[dict],
) -> dict:
    verification = verification or {}
    tool_trace = _tool_trace(tool_calls_log)
    tool_results = _tool_results(tool_calls_log)
    sample_type = infer_sample_type(tool_trace, draft_answer, final_answer, verification)
    quality_score = score_sample(
        tool_trace=tool_trace,
        sources=sources or [],
        final_answer=final_answer,
        verification=verification,
    )
    passed = 1 if verification.get("passed", False) else 0
    sample_id = str(uuid.uuid4())

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO agent_eval_samples (
          sample_id, session_id, user_id, question, tool_trace, tool_results,
          sources, draft_answer, final_answer, verification, passed,
          sample_type, quality_score, review_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sample_id,
            session_id,
            user_id,
            question,
            _json(tool_trace),
            _json(tool_results),
            _json(sources or []),
            draft_answer,
            final_answer,
            _json(verification),
            passed,
            sample_type,
            quality_score,
            REVIEW_PENDING,
        ),
    )
    row = conn.execute(
        "SELECT * FROM agent_eval_samples WHERE sample_id = ?",
        (sample_id,),
    ).fetchone()
    conn.commit()
    conn.close()
    return dict(row)


def list_eval_samples(
    *,
    sample_type: Optional[str] = None,
    review_status: Optional[str] = None,
    user_id: Optional[str] = None,
    min_score: float = 0,
    passed_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    where = []
    params = []
    if sample_type:
        where.append("sample_type = ?")
        params.append(sample_type)
    if review_status:
        where.append("review_status = ?")
        params.append(review_status)
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if min_score:
        where.append("quality_score >= ?")
        params.append(float(min_score))
    if passed_only:
        where.append("passed = 1")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    params.append(min(max(int(limit or 100), 1), 5000))

    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT *
        FROM agent_eval_samples
        {where_sql}
        ORDER BY quality_score DESC, created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    conn.close()
    return [decode_eval_sample(dict(row)) for row in rows]


def decode_eval_sample(row: dict) -> dict:
    for field, fallback in (
        ("tool_trace", []),
        ("tool_results", []),
        ("sources", []),
        ("verification", {}),
    ):
        row[field] = _safe_loads(row.get(field), fallback)
    return row


def to_training_record(row: dict, export_type: str) -> Optional[dict]:
    row = decode_eval_sample(dict(row))
    if export_type == SAMPLE_TOOL_CALL:
        if not row["tool_trace"]:
            return None
        return {
            "sample_id": row["sample_id"],
            "type": SAMPLE_TOOL_CALL,
            "input": row["question"],
            "target": [
                {"tool": item["tool"], "arguments": item.get("arguments") or {}}
                for item in row["tool_trace"]
            ],
            "quality_score": row["quality_score"],
        }
    if export_type == SAMPLE_ANSWER_GENERATION:
        return {
            "sample_id": row["sample_id"],
            "type": SAMPLE_ANSWER_GENERATION,
            "question": row["question"],
            "tool_results": row["tool_results"],
            "sources": row["sources"],
            "answer": row["final_answer"],
            "quality_score": row["quality_score"],
        }
    if export_type == SAMPLE_PREFERENCE:
        draft = (row.get("draft_answer") or "").strip()
        final = (row.get("final_answer") or "").strip()
        if not draft or not final or draft == final:
            return None
        return {
            "sample_id": row["sample_id"],
            "type": SAMPLE_PREFERENCE,
            "question": row["question"],
            "sources": row["sources"],
            "chosen": final,
            "rejected": draft,
            "verification": row["verification"],
            "quality_score": row["quality_score"],
        }
    raise ValueError(f"unsupported export_type: {export_type}")
