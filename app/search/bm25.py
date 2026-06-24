# -*- coding: utf-8 -*-
import os
import jieba
from typing import List, Dict, Optional, Sequence

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


def _tokenize_terms(text: str) -> List[str]:
    stopwords = _load_stopwords()
    return [t for t in jieba.cut(text) if t.strip() and t not in stopwords]


def _tokenize(text: str) -> str:
    """Return space-joined tokens for diagnostics and backward-compatible callers."""
    return " ".join(_tokenize_terms(text))


def _build_or_match_query(terms: Sequence[str]) -> str:
    parts = []
    for term in terms:
        term = str(term or "").strip()
        if not term:
            continue
        escaped = term.replace('"', '""')
        parts.append(f'"{escaped}"')
    return " OR ".join(parts)


def _search_match(
    match_query: str,
    user_id: Optional[str] = None,
    user_ids: Optional[Sequence[str]] = None,
    top_k: int = TOP_K,
) -> List[Dict]:
    match_query = (match_query or "").strip()
    if not match_query:
        return []

    conn = get_connection()
    params: list = [match_query]

    clean_user_ids = [str(uid).strip() for uid in (user_ids or []) if str(uid).strip()]
    if user_id and not clean_user_ids:
        clean_user_ids = [user_id]

    user_filter = ""
    if clean_user_ids:
        placeholders = ", ".join("?" for _ in clean_user_ids)
        user_filter = f"AND f.user_id IN ({placeholders})"
        params.extend(clean_user_ids)

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
    user_ids: Optional[Sequence[str]] = None,
    top_k: int = TOP_K,
) -> List[Dict]:
    """Search with a prebuilt SQLite FTS5 MATCH query."""
    return _search_match(match_query, user_id=user_id, user_ids=user_ids, top_k=top_k)


def search(
    query: str,
    user_id: Optional[str] = None,
    user_ids: Optional[Sequence[str]] = None,
    top_k: int = TOP_K,
) -> List[Dict]:
    match_query = _build_or_match_query(_tokenize_terms(query))
    return _search_match(match_query, user_id=user_id, user_ids=user_ids, top_k=top_k)
