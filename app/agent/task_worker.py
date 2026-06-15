# -*- coding: utf-8 -*-
"""In-process Agent Task worker MVP."""

import asyncio
import json
from collections import defaultdict
from typing import Optional

from app.agent.tools import execute_tool
from app.agent.tasks import (
    add_event,
    _now,
    list_steps,
    mark_stale_running_as_interrupted,
    next_pending_task,
    update_step,
    update_task,
)
from app.llm.client import chat
from app.memory.store import add_memory, search_memories, update_memory
from app.storage.db import get_connection

_worker_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def start_worker() -> None:
    global _worker_task, _stop_event
    if _worker_task and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker() -> None:
    if _stop_event:
        _stop_event.set()
    if _worker_task:
        try:
            await asyncio.wait_for(_worker_task, timeout=5)
        except Exception:
            pass


async def _worker_loop() -> None:
    while True:
        if _stop_event and _stop_event.is_set():
            return
        try:
            mark_stale_running_as_interrupted()
            task = next_pending_task()
            if task:
                await run_task(task["task_id"])
            else:
                await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)


async def run_task(task_id: str) -> None:
    task = update_task(task_id, status="running", started_at=_now(), heartbeat_at=_now(), error="")
    if not task or task["status"] == "canceled":
        return
    add_event(task_id, "task_started", {"task_type": task.get("task_type")})

    try:
        steps = list_steps(task_id)
        for step in steps:
            current = update_task(task_id, current_step_index=step["step_index"], heartbeat_at=_now())
            if current and current["status"] == "canceled":
                add_event(task_id, "task_canceled_observed", {})
                return
            if step["status"] == "completed":
                continue
            await _run_step(task, step)
            current = update_task(task_id, heartbeat_at=_now())
            if current and current["status"] == "canceled":
                add_event(task_id, "task_canceled_observed", {})
                return

        final_answer = _completed_synthesis(task_id) or await _synthesize_final_answer(task_id, task)
        update_task(
            task_id,
            status="completed",
            final_answer=final_answer,
            finished_at=_now(),
            heartbeat_at=_now(),
        )
        add_event(task_id, "task_completed", {"final_answer_preview": final_answer[:300]})
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        update_task(task_id, status="failed", error=error, finished_at=_now())
        add_event(task_id, "task_failed", {"error": error})


async def _run_step(task: dict, step: dict) -> None:
    update_step(step["step_id"], status="running", started_at=_now(), error="")
    update_task(task["task_id"], heartbeat_at=_now(), current_step_index=step["step_index"])
    add_event(
        task["task_id"],
        "step_started",
        {"step_index": step["step_index"], "title": step["title"], "tool_name": step["tool_name"]},
        step_id=step["step_id"],
    )
    try:
        tool_name = step["tool_name"]
        args = json.loads(step["tool_args"] or "{}")
        if tool_name == "synthesize":
            result = await _synthesize_final_answer(task["task_id"], task)
        elif tool_name == "build_meeting_memories":
            count = _build_meeting_memories(user_id=task.get("user_id"))
            result = f"长期主题记忆构建完成：{count} 条"
        else:
            result = execute_tool(tool_name, args, task.get("user_id"))
        update_step(step["step_id"], status="completed", result=result, finished_at=_now())
        update_task(task["task_id"], heartbeat_at=_now())
        add_event(
            task["task_id"],
            "step_completed",
            {"step_index": step["step_index"], "result_preview": result[:300]},
            step_id=step["step_id"],
        )
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        update_step(step["step_id"], status="failed", error=error, finished_at=_now())
        add_event(
            task["task_id"],
            "step_failed",
            {"step_index": step["step_index"], "error": error},
            step_id=step["step_id"],
        )
        raise


async def _synthesize_final_answer(task_id: str, task: dict) -> str:
    steps = list_steps(task_id)
    evidence = []
    for step in steps:
        if step["tool_name"] == "synthesize":
            continue
        result = step.get("result") or ""
        if result:
            evidence.append(f"## {step['title']}\n{result}")
    content = "\n\n".join(evidence) or "没有可用的中间结果。"
    messages = [
        {
            "role": "system",
            "content": (
                "你是会议复杂任务汇总助手。请基于各步骤结果回答用户原始问题。"
                "不要编造，信息不足时明确说明。输出结构化、可直接阅读的中文结论。"
            ),
        },
        {
            "role": "user",
            "content": f"用户问题：{task['question']}\n\n步骤结果：\n{content}",
        },
    ]
    return await chat(messages, temperature=0.2)


def _completed_synthesis(task_id: str) -> str:
    for step in list_steps(task_id):
        if step["tool_name"] == "synthesize" and step["status"] == "completed":
            return step.get("result") or ""
    return ""


def _load_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _upsert_topic_memory(user_id: str | None, subject: str, content: str, evidence: list[dict]) -> dict:
    existing = search_memories(
        query=subject,
        user_id=user_id,
        scope="meeting_topic",
        memory_type="topic",
        limit=5,
    )
    for row in existing:
        if row.get("subject") == subject:
            return update_memory(
                row["memory_id"],
                content=content,
                evidence=evidence,
                source_type="extracted_meeting",
                trust_score=max(float(row.get("trust_score") or 0.7), 0.75),
            )
    return add_memory(
        user_id=user_id,
        scope="meeting_topic",
        memory_type="topic",
        subject=subject,
        content=content,
        trust_score=0.75,
        source_type="extracted_meeting",
        evidence=evidence,
    )


def _build_meeting_memories(user_id: str | None = None, min_count: int = 2, limit: int = 50) -> int:
    conn = get_connection()
    params = []
    where = ""
    if user_id:
        where = "WHERE m.user_id = ?"
        params.append(user_id)
    rows = [dict(r) for r in conn.execute(
        f"""
        SELECT m.note_id, m.user_id, m.title, m.create_time, ms.summary, ms.topics
        FROM meeting_summaries ms
        JOIN meetings m ON m.note_id = ms.note_id
        {where}
        ORDER BY m.create_time ASC
        """,
        params,
    ).fetchall()]
    conn.close()

    groups: dict[tuple[str | None, str], list[dict]] = defaultdict(list)
    for row in rows:
        for topic in _load_json_list(row.get("topics")):
            topic = str(topic).strip()
            if topic:
                groups[(row.get("user_id"), topic)].append(row)

    saved = 0
    for uid_topic, topic_rows in groups.items():
        uid, topic = uid_topic
        if len(topic_rows) < min_count:
            continue
        topic_rows = topic_rows[:limit]
        first = (topic_rows[0].get("create_time") or "")[:10]
        last = (topic_rows[-1].get("create_time") or "")[:10]
        titles = "、".join((r.get("title") or "未命名会议") for r in topic_rows[:5])
        summaries = "；".join((r.get("summary") or "")[:120] for r in topic_rows[:4] if r.get("summary"))
        content = (
            f"主题“{topic}”在 {first} 至 {last} 的 {len(topic_rows)} 场会议中反复出现。"
            f"相关会议包括：{titles}。主要内容：{summaries}"
        )
        evidence = [
            {"note_id": r.get("note_id"), "title": r.get("title"), "create_time": r.get("create_time")}
            for r in topic_rows
        ]
        _upsert_topic_memory(uid, topic, content, evidence)
        saved += 1
    return saved
