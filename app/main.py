# -*- coding: utf-8 -*-
import asyncio
import json
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.qa.service import ask
from app.agent.loop import run_agent, run_agent_stream
from app.storage.db import get_connection, init_db

app = FastAPI(title="MeetAgent", description="会议智能问答系统")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    from app.agent.task_worker import start_worker
    start_worker()


@app.on_event("shutdown")
async def shutdown():
    from app.agent.task_worker import stop_worker
    await stop_worker()


# ---------- 请求 / 响应模型 ----------

class QARequest(BaseModel):
    question: str
    user_id: Optional[str] = None
    top_k: int = 8


class SourceItem(BaseModel):
    chunk_id: str
    note_id: str
    title: str
    create_time: str
    speaker: str
    chunk_index: int
    text: str


class QAResponse(BaseModel):
    answer: str
    sources: list[SourceItem]


class AgentRequest(BaseModel):
    question: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    max_turns: int = 10


class ToolCallItem(BaseModel):
    turn: int
    tool: str
    arguments: dict
    result_preview: str
    failed: bool = False
    status: str = "done"


class AgentResponse(BaseModel):
    answer: str
    tool_calls_log: list[ToolCallItem]
    sources: list[dict] = []
    verification: Optional[dict] = None
    session_id: str


class AgentTaskRequest(BaseModel):
    question: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    task_type: str = "topic_analysis"


def _vector_index_count() -> int:
    try:
        from app.embed.vector_store import count
        return count()
    except Exception:
        return 0


def _clamp_max_turns(value: int) -> int:
    return min(max(int(value), 1), 20)


async def _run_memory_stop_hooks(
    session_id: str,
    user_id: Optional[str],
    question: str,
    answer: str,
    tool_calls_log: list,
    sources: Optional[list] = None,
    verification: Optional[dict] = None,
    draft_answer: Optional[str] = None,
) -> dict:
    """Run post-answer memory hooks. Hook failures must not break chat."""
    from app.agent import session as sess
    from app.memory.extractor import extract_and_store_memories
    from app.memory.feedback import store_feedback_reflections
    from app.memory.reflexion import store_reflections

    result = {
        "session_summary_updated": False,
        "memories_extracted": 0,
        "reflections_stored": 0,
        "feedback_reflections_stored": 0,
    }
    try:
        result["session_summary_updated"] = await sess.maybe_update_summary(session_id)
    except Exception:
        result["session_summary_updated"] = False

    try:
        summary = sess.get_summary(session_id)
        memories = await extract_and_store_memories(
            session_id=session_id,
            user_id=user_id,
            question=question,
            answer=answer,
            tool_calls_log=tool_calls_log,
            session_summary=(summary or {}).get("summary", ""),
        )
        result["memories_extracted"] = len(memories)
    except Exception:
        result["memories_extracted"] = 0

    try:
        reflections = await store_reflections(
            session_id=session_id,
            user_id=user_id,
            question=question,
            answer=answer,
            tool_calls_log=tool_calls_log,
            sources=sources or [],
            verification=verification,
            draft_answer=draft_answer,
        )
        result["reflections_stored"] = len(reflections)
    except Exception:
        result["reflections_stored"] = 0

    try:
        feedback_reflections = await store_feedback_reflections(
            session_id=session_id,
            user_id=user_id,
            question=question,
            answer=answer,
            tool_calls_log=tool_calls_log,
            sources=sources or [],
            verification=verification,
        )
        result["feedback_reflections_stored"] = len(feedback_reflections)
    except Exception:
        result["feedback_reflections_stored"] = 0
    return result


def _schedule_memory_stop_hooks(
    session_id: str,
    user_id: Optional[str],
    question: str,
    answer: str,
    tool_calls_log: list,
    sources: Optional[list] = None,
    verification: Optional[dict] = None,
    draft_answer: Optional[str] = None,
) -> None:
    """Run memory hooks in the background so chat responses are not blocked."""
    task = asyncio.create_task(_run_memory_stop_hooks(
        session_id=session_id,
        user_id=user_id,
        question=question,
        answer=answer,
        tool_calls_log=tool_calls_log,
        sources=sources,
        verification=verification,
        draft_answer=draft_answer,
    ))

    def _consume_result(done_task: asyncio.Task) -> None:
        try:
            done_task.result()
        except Exception:
            pass

    task.add_done_callback(_consume_result)


def _record_agent_eval_sample(
    *,
    session_id: str,
    user_id: Optional[str],
    question: str,
    answer: str,
    tool_calls_log: list,
    sources: list,
    verification: Optional[dict],
    draft_answer: Optional[str] = None,
) -> None:
    """Persist eval/training sample. Failures must not break chat."""
    try:
        from app.agent.eval_samples import create_eval_sample
        create_eval_sample(
            session_id=session_id,
            user_id=user_id,
            question=question,
            tool_calls_log=tool_calls_log or [],
            sources=sources or [],
            draft_answer=draft_answer or answer,
            final_answer=answer,
            verification=verification or {},
        )
    except Exception:
        pass


# ---------- 路由 ----------

@app.post("/agent/qa", response_model=AgentResponse)
async def agent_qa(req: AgentRequest):
    from app.agent import session as sess
    from app.memory.retrieval import build_memory_message
    session_id, history = sess.get_or_create_compacted(req.session_id, req.user_id)
    memory_context = build_memory_message(req.question, req.user_id)
    max_turns = _clamp_max_turns(req.max_turns)
    result = await run_agent(
        req.question,
        user_id=req.user_id,
        history=history,
        memory_context=memory_context,
        max_turns=max_turns,
    )
    sess.append_turn(
        session_id,
        req.question,
        result["answer"],
        result["tool_calls_log"],
        verification=result.get("verification"),
    )
    _record_agent_eval_sample(
        session_id=session_id,
        user_id=req.user_id,
        question=req.question,
        answer=result["answer"],
        tool_calls_log=result["tool_calls_log"],
        sources=result.get("sources", []),
        verification=result.get("verification"),
        draft_answer=result.get("draft_answer"),
    )
    _schedule_memory_stop_hooks(
        session_id=session_id,
        user_id=req.user_id,
        question=req.question,
        answer=result["answer"],
        tool_calls_log=result["tool_calls_log"],
        sources=result.get("sources", []),
        verification=result.get("verification"),
        draft_answer=result.get("draft_answer"),
    )
    return {
        "answer": result["answer"],
        "tool_calls_log": result["tool_calls_log"],
        "sources": result.get("sources", []),
        "verification": result.get("verification"),
        "session_id": session_id,
    }


@app.get("/agent/session/{session_id}")
def get_session(session_id: str):
    from app.agent import session as sess
    messages = sess.get_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="session 不存在")
    return {"session_id": session_id, "messages": messages}


@app.get("/agent/session/{session_id}/summary")
def get_session_summary(session_id: str):
    from app.agent import session as sess
    summary = sess.get_summary(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail="session summary 不存在")
    return summary


@app.post("/agent/qa/stream")
async def agent_qa_stream(req: AgentRequest):
    """SSE 流式问答。事件格式：data: {json}\n\n
    事件类型：session_id / tool_start / tool_done / token / done / error
    """
    from app.agent import session as sess
    from app.memory.retrieval import build_memory_message

    session_id, history = sess.get_or_create_compacted(req.session_id, req.user_id)
    memory_context = build_memory_message(req.question, req.user_id)
    max_turns = _clamp_max_turns(req.max_turns)

    async def event_gen():
        yield f"data: {json.dumps({'type': 'session_id', 'session_id': session_id}, ensure_ascii=False)}\n\n"

        answer_parts: list[str] = []
        tool_calls_log: list = []
        sources: list = []
        verification: Optional[dict] = None

        try:
            async for event in run_agent_stream(
                req.question,
                user_id=req.user_id,
                history=history,
                memory_context=memory_context,
                max_turns=max_turns,
            ):
                if event["type"] == "token":
                    answer_parts.append(event["content"])
                elif event["type"] == "done":
                    tool_calls_log = event.get("tool_calls_log", [])
                    sources = event.get("sources", [])
                    verification = event.get("verification")
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
            return

        answer = "".join(answer_parts)
        if answer:
            sess.append_turn(
                session_id,
                req.question,
                answer,
                tool_calls_log,
                verification=verification,
            )
            _record_agent_eval_sample(
                session_id=session_id,
                user_id=req.user_id,
                question=req.question,
                answer=answer,
                tool_calls_log=tool_calls_log,
                sources=sources,
                verification=verification,
                draft_answer=answer,
            )
            _schedule_memory_stop_hooks(
                session_id=session_id,
                user_id=req.user_id,
                question=req.question,
                answer=answer,
                tool_calls_log=tool_calls_log,
                sources=sources,
                verification=verification,
                draft_answer=answer,
            )

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/agent/session/{session_id}")
def clear_session(session_id: str):
    from app.agent import session as sess
    sess.clear(session_id)
    return {"ok": True}


@app.get("/sessions")
def list_sessions(user_id: Optional[str] = None, limit: int = 50, offset: int = 0):
    from app.agent import session as sess
    return sess.list_sessions(limit=limit, offset=offset, user_id=user_id)


@app.get("/memories")
def list_memory_items(
    user_id: Optional[str] = None,
    query: str = "",
    include_inactive: bool = False,
    scope: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 50,
):
    from app.memory.store import list_memories, search_memories

    if query:
        return search_memories(
            query=query,
            user_id=user_id,
            include_inactive=include_inactive,
            scope=scope,
            memory_type=memory_type,
            limit=limit,
        )
    return list_memories(
        user_id=user_id,
        include_inactive=include_inactive,
        limit=limit,
    )


@app.post("/agent/tasks")
def create_agent_task(req: AgentTaskRequest):
    from app.agent.tasks import create_task
    return create_task(
        question=req.question,
        user_id=req.user_id,
        session_id=req.session_id,
        task_type=req.task_type,
    )


@app.get("/agent/tasks")
def list_agent_tasks(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    from app.agent.tasks import list_tasks
    return list_tasks(user_id=user_id, status=status, limit=limit, offset=offset)


@app.get("/agent/tasks/{task_id}")
def get_agent_task(task_id: str):
    from app.agent.tasks import get_task
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/agent/tasks/{task_id}/steps")
def get_agent_task_steps(task_id: str):
    from app.agent.tasks import get_task, list_steps
    if not get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return list_steps(task_id)


@app.get("/agent/tasks/{task_id}/events")
def get_agent_task_events(task_id: str, after_id: int = 0, limit: int = 200):
    from app.agent.tasks import get_task, list_events
    if not get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return list_events(task_id, after_id=after_id, limit=limit)


@app.get("/agent/tasks/{task_id}/events/stream")
async def stream_agent_task_events(task_id: str, after_id: int = 0):
    from app.agent.tasks import get_task, list_events

    if not get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_gen():
        last_id = after_id
        while True:
            task = get_task(task_id)
            events = list_events(task_id, after_id=last_id, limit=100)
            for event in events:
                last_id = max(last_id, int(event["id"]))
                yield f"data: {json.dumps({'type': 'event', 'event': event}, ensure_ascii=False)}\n\n"
            if task and task["status"] in ("completed", "failed", "canceled"):
                yield f"data: {json.dumps({'type': 'done', 'task': task}, ensure_ascii=False)}\n\n"
                return
            await asyncio.sleep(1)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/agent/tasks/{task_id}/cancel")
def cancel_agent_task(task_id: str):
    from app.agent.tasks import cancel_task
    task = cancel_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/agent/tasks/{task_id}/retry")
def retry_agent_task(task_id: str):
    from app.agent.tasks import retry_task
    task = retry_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.post("/agent/tasks/recover")
def recover_agent_tasks(timeout_seconds: int = 120):
    from app.agent.tasks import recover_interrupted_tasks
    return {"recovered": recover_interrupted_tasks(timeout_seconds=timeout_seconds)}


@app.post("/qa", response_model=QAResponse)
async def qa(req: QARequest):
    result = await ask(req.question, user_id=req.user_id, top_k=req.top_k)
    return result


@app.get("/stats")
def get_stats(include_vector: bool = False):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM meetings) AS meetings,
          (SELECT COUNT(*) FROM chunks) AS chunks,
          (SELECT COUNT(*) FROM meeting_summaries) AS summaries,
          (SELECT COUNT(*) FROM action_items) AS action_items,
          (SELECT COUNT(*) FROM decisions) AS decisions,
          (SELECT COUNT(*) FROM risks) AS risks,
          (SELECT COUNT(*) FROM entities) AS entities,
          (SELECT COUNT(*) FROM chat_sessions) AS chat_sessions,
          (SELECT COUNT(*) FROM session_summaries) AS session_summaries,
          (SELECT COUNT(*) FROM memories) AS memories,
          (SELECT COUNT(*) FROM agent_tasks) AS agent_tasks
        """
    ).fetchone()
    conn.close()
    data = dict(row)
    data["vector_index_count"] = _vector_index_count() if include_vector else None
    return data


@app.get("/vector/stats")
def get_vector_stats():
    return {"vector_index_count": _vector_index_count()}


@app.get("/config/status")
def get_config_status():
    from app.config import APIFUSION_API_KEY, TAVILY_API_KEY
    return {
        "llm_configured": bool(APIFUSION_API_KEY),
        "web_search_configured": bool(TAVILY_API_KEY),
    }


@app.get("/users")
def list_users():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
          m.user_id,
          COUNT(DISTINCT m.note_id) AS meetings,
          COUNT(DISTINCT c.chunk_id) AS chunks,
          COUNT(DISTINCT s.note_id) AS summaries,
          MIN(m.create_time) AS earliest,
          MAX(m.create_time) AS latest
        FROM meetings m
        LEFT JOIN chunks c ON c.note_id = m.note_id
        LEFT JOIN meeting_summaries s ON s.note_id = m.note_id
        GROUP BY m.user_id
        ORDER BY meetings DESC, m.user_id ASC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/users/{user_id}/meetings")
def list_user_meetings(user_id: str, limit: int = 100, offset: int = 0):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
          m.note_id,
          m.user_id,
          m.title,
          m.create_time,
          m.duration_minutes,
          m.language,
          COUNT(c.chunk_id) AS chunks,
          CASE WHEN s.note_id IS NULL THEN 0 ELSE 1 END AS extracted
        FROM meetings m
        LEFT JOIN chunks c ON c.note_id = m.note_id
        LEFT JOIN meeting_summaries s ON s.note_id = m.note_id
        WHERE m.user_id = ?
        GROUP BY m.note_id
        ORDER BY m.create_time DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/meetings")
def list_meetings(user_id: Optional[str] = None, limit: int = 50, offset: int = 0):
    conn = get_connection()
    if user_id:
        rows = conn.execute(
            "SELECT note_id, user_id, title, create_time, duration_minutes, language "
            "FROM meetings WHERE user_id = ? ORDER BY create_time DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT note_id, user_id, title, create_time, duration_minutes, language "
            "FROM meetings ORDER BY create_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/meetings/{note_id}")
def get_meeting(note_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM meetings WHERE note_id = ?", (note_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="会议不存在")
    return dict(row)


@app.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="片段不存在")
    return dict(row)
