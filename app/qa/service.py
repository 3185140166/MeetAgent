# -*- coding: utf-8 -*-
from typing import Optional
from app.search.bm25 import search
from app.llm.client import chat
from app.qa.prompts import build_messages
from app.config import TOP_K


async def ask(
    question: str,
    user_id: Optional[str] = None,
    top_k: int = TOP_K,
) -> dict:
    chunks = search(question, user_id=user_id, top_k=top_k)
    if not chunks:
        return {
            "answer": "当前会议资料中没有找到相关内容。",
            "sources": [],
        }

    messages = build_messages(question, chunks)
    answer = await chat(messages)

    sources = [
        {
            "chunk_id": c["chunk_id"],
            "note_id": c["note_id"],
            "title": c["title"],
            "create_time": c["create_time"],
            "speaker": c["speaker"],
            "chunk_index": c["chunk_index"],
            "text": c["text"],
        }
        for c in chunks
    ]

    return {"answer": answer, "sources": sources}
