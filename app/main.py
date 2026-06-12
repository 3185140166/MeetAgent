# -*- coding: utf-8 -*-
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.qa.service import ask
from app.agent.loop import run_agent
from app.storage.db import get_connection, init_db

app = FastAPI(title="MeetAgent", description="会议智能问答系统")


@app.on_event("startup")
def startup():
    init_db()


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
    max_turns: int = 5


class ToolCallItem(BaseModel):
    turn: int
    tool: str
    arguments: dict
    result_preview: str


class AgentResponse(BaseModel):
    answer: str
    tool_calls_log: list[ToolCallItem]
    session_id: str


# ---------- 路由 ----------

@app.post("/agent/qa", response_model=AgentResponse)
async def agent_qa(req: AgentRequest):
    from app.agent import session as sess
    session_id, history = sess.get_or_create(req.session_id, req.user_id)
    result = await run_agent(
        req.question, user_id=req.user_id, history=history, max_turns=req.max_turns
    )
    sess.append_turn(session_id, req.question, result["answer"], result["tool_calls_log"])
    return {
        "answer": result["answer"],
        "tool_calls_log": result["tool_calls_log"],
        "session_id": session_id,
    }


@app.get("/agent/session/{session_id}")
def get_session(session_id: str):
    from app.agent import session as sess
    messages = sess.get_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="session 不存在或已过期")
    return {"session_id": session_id, "messages": messages}


@app.delete("/agent/session/{session_id}")
def clear_session(session_id: str):
    from app.agent import session as sess
    sess.clear(session_id)
    return {"ok": True}


@app.post("/qa", response_model=QAResponse)
async def qa(req: QARequest):
    result = await ask(req.question, user_id=req.user_id, top_k=req.top_k)
    return result


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
