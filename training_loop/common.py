# -*- coding: utf-8 -*-
"""Shared helpers for offline training-loop tools."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "meetagent.db"

VALID_REVIEW_STATUSES = {"pending", "accepted", "rejected", "fixed"}
VALID_EXPORT_TYPES = {"tool_call", "answer_generation", "preference", "all"}


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def load_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def dump_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def decode_sample(row: sqlite3.Row | dict) -> dict:
    item = dict(row)
    for field, fallback in (
        ("tool_trace", []),
        ("tool_results", []),
        ("sources", []),
        ("verification", {}),
    ):
        item[field] = load_json(item.get(field), fallback)
    return item


def has_failed_tool(sample: dict) -> bool:
    return any(bool(item.get("failed")) for item in sample.get("tool_trace") or [])


def has_sources(sample: dict) -> bool:
    return bool(sample.get("sources"))


def iter_samples(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    sample_type: str | None = None,
    review_status: str | None = None,
    user_id: str | None = None,
    min_score: float = 0,
    passed_only: bool = False,
    no_failed_tools: bool = False,
    require_sources: bool = False,
    limit: int = 1000,
) -> list[dict]:
    where = []
    params: list[Any] = []
    if sample_type and sample_type != "all":
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
    params.append(min(max(int(limit or 1000), 1), 10000))

    conn = connect(db_path)
    try:
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
    finally:
        conn.close()

    samples = [decode_sample(row) for row in rows]
    if no_failed_tools:
        samples = [sample for sample in samples if not has_failed_tool(sample)]
    if require_sources:
        samples = [sample for sample in samples if has_sources(sample)]
    return samples


def update_review_status(
    sample_id: str,
    status: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    if status not in VALID_REVIEW_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_REVIEW_STATUSES)}")
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE agent_eval_samples SET review_status = ? WHERE sample_id = ?",
            (status, sample_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
