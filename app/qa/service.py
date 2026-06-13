# -*- coding: utf-8 -*-
from typing import Optional
from app.llm.client import chat
from app.qa.prompts import build_messages
from app.config import ENABLE_HYBRID_SEARCH, TOP_K


def _do_search(question: str, user_id: Optional[str], top_k: int):
    """优先使用混合检索；向量库为空时自动降级到 BM25。"""
    if ENABLE_HYBRID_SEARCH:
        try:
            from app.embed.vector_store import count
            if count() > 0:
                from app.search.hybrid import search as hybrid_search
                return hybrid_search(question, user_id=user_id, top_k=top_k)
        except Exception:
            pass
    from app.search.bm25 import search as bm25_search
    return bm25_search(question, user_id=user_id, top_k=top_k)


async def ask(
    question: str,
    user_id: Optional[str] = None,
    top_k: int = TOP_K,
) -> dict:
    chunks = _do_search(question, user_id, top_k)
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
            "title": c.get("title", ""),
            "create_time": c.get("create_time", ""),
            "speaker": c.get("speaker", ""),
            "chunk_index": c.get("chunk_index", -1),
            "text": c["text"],
        }
        for c in chunks
    ]

    return {"answer": answer, "sources": sources}
