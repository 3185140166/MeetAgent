# -*- coding: utf-8 -*-
"""Long-term memory CRUD and keyword retrieval."""

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from app.storage.db import get_connection

ACTIVE_STATUS = "active"
INACTIVE_STATUSES = {"deprecated", "deleted", "expired"}
VALID_STATUSES = {ACTIVE_STATUS, *INACTIVE_STATUSES}
VALID_SCOPES = {"user", "project", "meeting_topic"}
VALID_MEMORY_TYPES = {"preference", "fact", "task", "topic", "decision", "risk"}


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _json_dumps(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _normalize_scope(scope: str) -> str:
    scope = (scope or "user").strip()
    if scope not in VALID_SCOPES:
        raise ValueError(f"scope 只支持: {', '.join(sorted(VALID_SCOPES))}")
    return scope


def _normalize_memory_type(memory_type: str) -> str:
    memory_type = (memory_type or "fact").strip()
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"memory_type 只支持: {', '.join(sorted(VALID_MEMORY_TYPES))}")
    return memory_type


def _normalize_status(status: str) -> str:
    status = (status or ACTIVE_STATUS).strip()
    if status not in VALID_STATUSES:
        raise ValueError(f"status 只支持: {', '.join(sorted(VALID_STATUSES))}")
    return status


def _sync_fts(conn, memory_id: str, user_id: Optional[str], subject: str, content: str, status: str) -> None:
    conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
    if status == ACTIVE_STATUS:
        conn.execute(
            "INSERT INTO memory_fts (memory_id, user_id, subject, content) VALUES (?, ?, ?, ?)",
            (memory_id, user_id, subject or "", content),
        )


def add_memory(
    *,
    user_id: Optional[str],
    content: str,
    scope: str = "user",
    memory_type: str = "fact",
    subject: str = "",
    trust_score: float = 0.7,
    source_type: str = "manual",
    source_id: str = "",
    evidence: Any = None,
    expires_at: str = "",
    memory_id: Optional[str] = None,
) -> dict:
    """新增长期记忆，并同步 FTS。"""
    content = (content or "").strip()
    if not content:
        raise ValueError("content 不能为空")

    scope = _normalize_scope(scope)
    memory_type = _normalize_memory_type(memory_type)
    memory_id = memory_id or str(uuid.uuid4())
    now = _now()
    evidence_json = _json_dumps(evidence)

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO memories (
          memory_id, user_id, scope, memory_type, subject, content, status,
          trust_score, source_type, source_id, evidence, created_at, updated_at, expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            memory_id,
            user_id,
            scope,
            memory_type,
            subject or "",
            content,
            float(trust_score),
            source_type or "",
            source_id or "",
            evidence_json,
            now,
            now,
            expires_at or "",
        ),
    )
    _sync_fts(conn, memory_id, user_id, subject or "", content, ACTIVE_STATUS)
    conn.commit()
    row = get_memory(memory_id, conn=conn)
    conn.close()
    return row


def get_memory(memory_id: str, conn=None) -> Optional[dict]:
    own_conn = conn is None
    conn = conn or get_connection()
    row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
    if own_conn:
        conn.close()
    return dict(row) if row else None


def update_memory(memory_id: str, **fields) -> Optional[dict]:
    """更新长期记忆。支持 content/subject/status/trust_score 等字段，并同步 FTS。"""
    allowed = {
        "user_id", "scope", "memory_type", "subject", "content", "status",
        "trust_score", "source_type", "source_id", "evidence", "expires_at",
    }
    updates = {}
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "scope":
            value = _normalize_scope(value)
        elif key == "memory_type":
            value = _normalize_memory_type(value)
        elif key == "status":
            value = _normalize_status(value)
        elif key == "evidence":
            value = _json_dumps(value)
        updates[key] = value

    if not updates:
        return get_memory(memory_id)
    updates["updated_at"] = _now()

    assignments = ", ".join(f"{key} = ?" for key in updates)
    params = list(updates.values()) + [memory_id]

    conn = get_connection()
    conn.execute(f"UPDATE memories SET {assignments} WHERE memory_id = ?", params)
    row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
    if row:
        row_dict = dict(row)
        _sync_fts(
            conn,
            memory_id,
            row_dict.get("user_id"),
            row_dict.get("subject") or "",
            row_dict.get("content") or "",
            row_dict.get("status") or ACTIVE_STATUS,
        )
    conn.commit()
    result = dict(row) if row else None
    conn.close()
    return result


def set_status(memory_id: str, status: str) -> Optional[dict]:
    return update_memory(memory_id, status=status)


def mark_deprecated(memory_id: str) -> Optional[dict]:
    return set_status(memory_id, "deprecated")


def mark_deleted(memory_id: str) -> Optional[dict]:
    return set_status(memory_id, "deleted")


def adjust_trust(memory_id: str, delta: float) -> Optional[dict]:
    row = get_memory(memory_id)
    if not row:
        return None
    trust = min(max(float(row.get("trust_score") or 0.7) + float(delta), 0.0), 1.0)
    return update_memory(memory_id, trust_score=trust)


def search_memories(
    *,
    query: str = "",
    user_id: Optional[str] = None,
    include_inactive: bool = False,
    scope: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """关键词检索长期记忆。默认只返回 active 记忆。"""
    limit = min(max(int(limit or 10), 1), 50)
    params: list[Any] = []
    where = []

    if user_id:
        where.append("m.user_id = ?")
        params.append(user_id)
    if not include_inactive:
        where.append("m.status = 'active'")
    if scope:
        where.append("m.scope = ?")
        params.append(_normalize_scope(scope))
    if memory_type:
        where.append("m.memory_type = ?")
        params.append(_normalize_memory_type(memory_type))

    query = (query or "").strip()
    if query:
        like = f"%{query}%"
        where.append("(m.subject LIKE ? OR m.content LIKE ?)")
        params.extend([like, like])

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    params.append(limit)

    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT m.*
        FROM memories m
        {where_sql}
        ORDER BY m.trust_score DESC, m.updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    if query:
        try:
            fts_where = []
            fts_params: list[Any] = [query]
            if user_id:
                fts_where.append("m.user_id = ?")
                fts_params.append(user_id)
            if not include_inactive:
                fts_where.append("m.status = 'active'")
            if scope:
                fts_where.append("m.scope = ?")
                fts_params.append(_normalize_scope(scope))
            if memory_type:
                fts_where.append("m.memory_type = ?")
                fts_params.append(_normalize_memory_type(memory_type))
            fts_where_sql = " AND " + " AND ".join(fts_where) if fts_where else ""
            fts_params.append(limit)
            fts_rows = conn.execute(
                f"""
                SELECT m.*
                FROM memory_fts f
                JOIN memories m ON m.memory_id = f.memory_id
                WHERE memory_fts MATCH ? {fts_where_sql}
                ORDER BY m.trust_score DESC, m.updated_at DESC
                LIMIT ?
                """,
                fts_params,
            ).fetchall()
            by_id = {r["memory_id"]: dict(r) for r in fts_rows}
            for r in rows:
                by_id.setdefault(r["memory_id"], dict(r))
            conn.close()
            return list(by_id.values())[:limit]
        except Exception:
            pass

    conn.close()
    return [dict(r) for r in rows]


def find_similar_memories(
    *,
    user_id: Optional[str],
    subject: str = "",
    content: str = "",
    scope: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    """Find active memories that may overlap a new candidate."""
    query_parts = [p for p in [subject, content] if p]
    query = " ".join(query_parts[:2]).strip()
    if not query:
        return []
    return search_memories(
        query=query,
        user_id=user_id,
        include_inactive=False,
        scope=scope,
        memory_type=memory_type,
        limit=limit,
    )


def list_memories(
    *,
    user_id: Optional[str] = None,
    include_inactive: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    limit = min(max(int(limit or 50), 1), 200)
    offset = max(int(offset or 0), 0)
    params: list[Any] = []
    where = []
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if not include_inactive:
        where.append("status = 'active'")
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    params.extend([limit, offset])

    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT *
        FROM memories
        {where_sql}
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def rebuild_fts() -> int:
    """按 active memories 重建 memory_fts。"""
    conn = get_connection()
    conn.execute("DELETE FROM memory_fts")
    rows = conn.execute(
        "SELECT memory_id, user_id, subject, content FROM memories WHERE status = 'active'"
    ).fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO memory_fts (memory_id, user_id, subject, content) VALUES (?, ?, ?, ?)",
            (r["memory_id"], r["user_id"], r["subject"] or "", r["content"]),
        )
    conn.commit()
    count = len(rows)
    conn.close()
    return count
