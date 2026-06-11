# -*- coding: utf-8 -*-
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.qa.service import ask
from app.storage.db import get_connection

app = FastAPI(title="MeetAgent", description="会议智能问答系统")


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


# ---------- 路由 ----------

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
