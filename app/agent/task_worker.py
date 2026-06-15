# -*- coding: utf-8 -*-
"""In-process Agent Task worker MVP."""

import asyncio
import json
from typing import Optional

from app.agent.tools import execute_tool
from app.agent.tasks import (
    _now,
    list_steps,
    mark_stale_running_as_interrupted,
    next_pending_task,
    update_step,
    update_task,
)
from app.llm.client import chat

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

    try:
        steps = list_steps(task_id)
        for step in steps:
            current = update_task(task_id, current_step_index=step["step_index"], heartbeat_at=_now())
            if current and current["status"] == "canceled":
                return
            if step["status"] == "completed":
                continue
            await _run_step(task, step)
            current = update_task(task_id, heartbeat_at=_now())
            if current and current["status"] == "canceled":
                return

        final_answer = _completed_synthesis(task_id) or await _synthesize_final_answer(task_id, task)
        update_task(
            task_id,
            status="completed",
            final_answer=final_answer,
            finished_at=_now(),
            heartbeat_at=_now(),
        )
    except Exception as e:
        update_task(task_id, status="failed", error=f"{type(e).__name__}: {e}", finished_at=_now())


async def _run_step(task: dict, step: dict) -> None:
    update_step(step["step_id"], status="running", started_at=_now(), error="")
    update_task(task["task_id"], heartbeat_at=_now(), current_step_index=step["step_index"])
    try:
        tool_name = step["tool_name"]
        args = json.loads(step["tool_args"] or "{}")
        if tool_name == "synthesize":
            result = await _synthesize_final_answer(task["task_id"], task)
        else:
            result = execute_tool(tool_name, args, task.get("user_id"))
        update_step(step["step_id"], status="completed", result=result, finished_at=_now())
        update_task(task["task_id"], heartbeat_at=_now())
    except Exception as e:
        update_step(step["step_id"], status="failed", error=f"{type(e).__name__}: {e}", finished_at=_now())
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
