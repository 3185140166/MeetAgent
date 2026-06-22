# -*- coding: utf-8 -*-
import os
import jieba
from typing import List, Dict, Optional

from app.storage.db import get_connection
from app.config import TOP_K

_stopwords: Optional[set] = None


def _load_stopwords() -> set:
    global _stopwords
    if _stopwords is not None:
        return _stopwords
    path = os.path.join("data", "stopwords.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            _stopwords = {line.strip() for line in f if line.strip()}
    else:
        _stopwords = set()
    return _stopwords


def _tokenize(text: str) -> str:
    stopwords = _load_stopwords()
    tokens = [t for t in jieba.cut(text) if t.strip() and t not in stopwords]
    return " ".join(tokens)


def _search_match(
    match_query: str,
    user_id: Optional[str] = None,
    top_k: int = TOP_K,
) -> List[Dict]:
    match_query = (match_query or "").strip()
    if not match_query:
        return []

    conn = get_connection()
    params: list = [match_query]

    user_filter = ""
    if user_id:
        user_filter = "AND f.user_id = ?"
        params.append(user_id)

    params.append(top_k)

    sql = f"""
        SELECT
            f.chunk_id,
            f.note_id,
            f.user_id,
            -bm25(fts_chunks) AS score,
            c.chunk_index,
            c.speaker,
            c.text,
            m.title,
            m.create_time
        FROM fts_chunks f
        JOIN chunks c ON c.chunk_id = f.chunk_id
        JOIN meetings m ON m.note_id = f.note_id
        WHERE fts_chunks MATCH ?
        {user_filter}
        ORDER BY bm25(fts_chunks)
        LIMIT ?
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def search_match_query(
    match_query: str,
    user_id: Optional[str] = None,
    top_k: int = TOP_K,
) -> List[Dict]:
    """Search with a prebuilt SQLite FTS5 MATCH query."""
    return _search_match(match_query, user_id=user_id, top_k=top_k)


def search(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = TOP_K,
) -> List[Dict]:
    query_tokens = _tokenize(query)
    return _search_match(query_tokens, user_id=user_id, top_k=top_k)
