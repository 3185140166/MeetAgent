# -*- coding: utf-8 -*-
"""Persistent Agent Task storage for long-running complex tasks."""

import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

from app.storage.db import get_connection

TASK_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
    "interrupted",
    "canceled",
}
STEP_STATUSES = {"pending", "running", "completed", "failed", "skipped"}
TASK_TYPES = {"topic_analysis", "weekly_report", "memory_build"}


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _task_plan(question: str, topic: str, task_type: str) -> tuple[str, list[dict]]:
    if task_type == "weekly_report":
        plan = [
            {"title": "生成周报素材", "tool_name": "query_meeting_records", "tool_args": {"record_type": "weekly_report"}},
            {"title": "生成周报结论", "tool_name": "synthesize", "tool_args": {"question": question}},
        ]
    elif task_type == "memory_build":
        plan = [
            {"title": "构建长期主题记忆", "tool_name": "build_meeting_memories", "tool_args": {}},
            {"title": "生成执行摘要", "tool_name": "synthesize", "tool_args": {"question": question}},
        ]
    else:
        plan = [
            {"title": "追踪主题历史", "tool_name": "query_meeting_records", "tool_args": {"record_type": "topic_history", "topic": topic, "limit": 20}},
            {"title": "汇总相关决策", "tool_name": "query_meeting_records", "tool_args": {"record_type": "decisions", "keyword": topic}},
            {"title": "汇总相关风险", "tool_name": "query_meeting_records", "tool_args": {"record_type": "risks", "keyword": topic}},
            {"title": "汇总相关待办", "tool_name": "query_meeting_records", "tool_args": {"record_type": "action_items", "keyword": topic}},
            {"title": "生成综合分析", "tool_name": "synthesize", "tool_args": {"question": question}},
        ]
    return _json(plan), plan


def infer_topic(question: str) -> str:
    """MVP topic inference: keep the original question as retrieval query."""
    text = (question or "").strip()
    return text[:80] if text else "主题分析"


def create_task(
    *,
    question: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    task_type: str = "topic_analysis",
) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("question 不能为空")
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type 只支持: {', '.join(sorted(TASK_TYPES))}")

    task_id = str(uuid.uuid4())
    now = _now()
    topic = infer_topic(question)
    plan_json, steps = _task_plan(question, topic, task_type)

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO agent_tasks (
          task_id, session_id, user_id, question, task_type, status, plan,
          current_step_index, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?, 0, ?, ?)
        """,
        (task_id, session_id, user_id, question, task_type, plan_json, now, now),
    )
    for index, step in enumerate(steps, 1):
        conn.execute(
            """
            INSERT INTO agent_task_steps (
              step_id, task_id, step_index, title, description, tool_name,
              tool_args, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                str(uuid.uuid4()),
                task_id,
                index,
                step["title"],
                step.get("description", ""),
                step["tool_name"],
                _json(step.get("tool_args", {})),
            ),
        )
    add_event(task_id, "task_created", {"task_type": task_type, "step_count": len(steps)}, conn=conn)
    conn.commit()
    row = get_task(task_id, conn=conn)
    conn.close()
    return row


def get_task(task_id: str, conn=None) -> Optional[dict]:
    own = conn is None
    conn = conn or get_connection()
    row = conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
    if own:
        conn.close()
    return dict(row) if row else None


def list_tasks(
    *,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    limit = min(max(int(limit or 50), 1), 200)
    offset = max(int(offset or 0), 0)
    where = []
    params = []
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if status:
        where.append("status = ?")
        params.append(status)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    params.extend([limit, offset])

    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT *
        FROM agent_tasks
        {where_sql}
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_steps(task_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM agent_task_steps WHERE task_id = ? ORDER BY step_index",
        (task_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_event(
    task_id: str,
    event_type: str,
    payload=None,
    step_id: Optional[str] = None,
    conn=None,
) -> dict:
    own = conn is None
    conn = conn or get_connection()
    conn.execute(
        """
        INSERT INTO agent_task_events (task_id, step_id, event_type, payload, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (task_id, step_id, event_type, _json(payload or {}), _now()),
    )
    row = conn.execute(
        "SELECT * FROM agent_task_events WHERE id = last_insert_rowid()"
    ).fetchone()
    if own:
        conn.commit()
        conn.close()
    return dict(row)


def list_events(task_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
    limit = min(max(int(limit or 200), 1), 500)
    after_id = max(int(after_id or 0), 0)
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT *
        FROM agent_task_events
        WHERE task_id = ? AND id > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (task_id, after_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.get("payload") or "{}")
        except Exception:
            item["payload"] = {}
        result.append(item)
    return result


def update_task(task_id: str, **fields) -> Optional[dict]:
    allowed = {
        "status",
        "plan",
        "final_answer",
        "error",
        "current_step_index",
        "started_at",
        "finished_at",
        "heartbeat_at",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "status" in updates and updates["status"] not in TASK_STATUSES:
        raise ValueError(f"非法 task status: {updates['status']}")
    if not updates:
        return get_task(task_id)
    updates["updated_at"] = _now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    params = list(updates.values()) + [task_id]
    conn = get_connection()
    conn.execute(f"UPDATE agent_tasks SET {assignments} WHERE task_id = ?", params)
    conn.commit()
    row = get_task(task_id, conn=conn)
    conn.close()
    return row


def update_step(step_id: str, **fields) -> Optional[dict]:
    allowed = {"status", "result", "error", "started_at", "finished_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if "status" in updates and updates["status"] not in STEP_STATUSES:
        raise ValueError(f"非法 step status: {updates['status']}")
    if not updates:
        return None
    assignments = ", ".join(f"{key} = ?" for key in updates)
    params = list(updates.values()) + [step_id]
    conn = get_connection()
    conn.execute(f"UPDATE agent_task_steps SET {assignments} WHERE step_id = ?", params)
    row = conn.execute("SELECT * FROM agent_task_steps WHERE step_id = ?", (step_id,)).fetchone()
    conn.commit()
    result = dict(row) if row else None
    conn.close()
    return result


def next_pending_task() -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        """
        SELECT *
        FROM agent_tasks
        WHERE status IN ('pending', 'interrupted')
        ORDER BY created_at ASC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_stale_running_as_interrupted(timeout_seconds: int = 120) -> int:
    cutoff = (datetime.utcnow() - timedelta(seconds=timeout_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT task_id
        FROM agent_tasks
        WHERE status = 'running'
          AND (heartbeat_at IS NULL OR heartbeat_at < ?)
        """,
        (cutoff,),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            UPDATE agent_tasks
            SET status = 'interrupted', updated_at = ?, error = COALESCE(error, '')
            WHERE task_id = ?
            """,
            (_now(), row["task_id"]),
        )
        conn.execute(
            """
            UPDATE agent_task_steps
            SET status = 'pending', error = ''
            WHERE task_id = ? AND status = 'running'
            """,
            (row["task_id"],),
        )
        add_event(row["task_id"], "task_interrupted", {"reason": "heartbeat_timeout"}, conn=conn)
    conn.commit()
    count = len(rows)
    conn.close()
    return count


def cancel_task(task_id: str) -> Optional[dict]:
    task = update_task(task_id, status="canceled", finished_at=_now())
    if task:
        add_event(task_id, "task_canceled", {})
    return task


def retry_task(task_id: str) -> Optional[dict]:
    task = get_task(task_id)
    if not task:
        return None
    if task["status"] not in {"failed", "interrupted", "canceled"}:
        return task
    conn = get_connection()
    conn.execute(
        """
        UPDATE agent_task_steps
        SET status = 'pending', error = '', started_at = NULL, finished_at = NULL
        WHERE task_id = ? AND status IN ('failed', 'running', 'pending')
        """,
        (task_id,),
    )
    conn.execute(
        """
        UPDATE agent_tasks
        SET status = 'pending', error = '', final_answer = NULL,
            finished_at = NULL, updated_at = ?, heartbeat_at = NULL
        WHERE task_id = ?
        """,
        (_now(), task_id),
    )
    add_event(task_id, "task_retried", {"from_status": task["status"]}, conn=conn)
    conn.commit()
    row = get_task(task_id, conn=conn)
    conn.close()
    return row


def recover_interrupted_tasks(timeout_seconds: int = 120) -> int:
    interrupted = mark_stale_running_as_interrupted(timeout_seconds=timeout_seconds)
    conn = get_connection()
    rows = conn.execute(
        "SELECT task_id FROM agent_tasks WHERE status = 'interrupted'"
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            UPDATE agent_tasks
            SET status = 'pending', updated_at = ?, heartbeat_at = NULL
            WHERE task_id = ?
            """,
            (_now(), row["task_id"]),
        )
        conn.execute(
            """
            UPDATE agent_task_steps
            SET status = 'pending', error = ''
            WHERE task_id = ? AND status = 'running'
            """,
            (row["task_id"],),
        )
        add_event(row["task_id"], "task_recovered", {}, conn=conn)
    conn.commit()
    recovered = len(rows)
    conn.close()
    return interrupted + recovered
