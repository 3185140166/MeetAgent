# -*- coding: utf-8 -*-
"""Retrieval baselines for offline algorithm experiments."""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

RRF_K = 60


def _hit_key(hit: dict) -> str:
    return hit.get("chunk_id") or f"{hit.get('note_id', '')}:{hit.get('text', '')[:80]}"


def _dedupe_hits(hits: Iterable[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for hit in hits:
        key = _hit_key(hit)
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(hit))
    return result


def _rrf_merge(query_hits: list[tuple[str, list[dict]]], top_k: int) -> list[dict]:
    scores: dict[str, float] = {}
    hits_by_key: dict[str, dict] = {}
    matched_queries: dict[str, list[str]] = {}

    for query, hits in query_hits:
        for rank, hit in enumerate(hits, 1):
            key = _hit_key(hit)
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_K + rank)
            if key not in hits_by_key:
                hits_by_key[key] = dict(hit)
                matched_queries[key] = []
            matched_queries[key].append(query)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
    merged: list[dict] = []
    for key, score in ranked:
        hit = dict(hits_by_key[key])
        hit["multi_rrf_score"] = score
        hit["matched_queries"] = matched_queries.get(key, [])
        merged.append(hit)
    return merged


UserFilter = str | Sequence[str] | None


def _user_filter_kwargs(user_filter: UserFilter) -> dict:
    if user_filter is None or isinstance(user_filter, str):
        return {"user_id": user_filter}
    return {"user_ids": list(user_filter)}


def bm25(query: str, user_id: UserFilter = None, top_k: int = 8) -> list[dict]:
    from app.search.bm25 import search as bm25_search

    return _dedupe_hits(bm25_search(query, top_k=top_k, **_user_filter_kwargs(user_id)))


def llm_sparse_bm25(query: str, user_id: UserFilter = None, top_k: int = 8) -> list[dict]:
    from app.search.bm25 import search_match_query as bm25_search_match_query
    from app.search.sparse_query import build_llm_sparse_match_query

    match_query, sparse_terms = build_llm_sparse_match_query(query)
    if not match_query:
        return bm25(query, user_id=user_id, top_k=top_k)
    hits = bm25_search_match_query(match_query, top_k=top_k, **_user_filter_kwargs(user_id))
    for hit in hits:
        hit["sparse_query"] = match_query
        hit["sparse_terms"] = sparse_terms
    return _dedupe_hits(hits)


def dense(query: str, user_id: UserFilter = None, top_k: int = 8) -> list[dict]:
    from app.embed.encoder import embed_one
    from app.embed.vector_store import search as vector_search

    query_vec = embed_one(query)
    return _dedupe_hits(vector_search(query_vec, top_k=top_k, **_user_filter_kwargs(user_id)))


def hybrid_rrf(query: str, user_id: UserFilter = None, top_k: int = 8) -> list[dict]:
    from app.search.hybrid import search as hybrid_search

    return _dedupe_hits(hybrid_search(query, top_k=top_k, **_user_filter_kwargs(user_id)))


def multi_query(
    queries: list[str],
    user_id: UserFilter,
    top_k: int,
    search_fn: Callable[[str, UserFilter, int], list[dict]],
) -> list[dict]:
    clean_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        query = str(query or "").strip()
        if not query or query in seen:
            continue
        seen.add(query)
        clean_queries.append(query)

    query_hits = [
        (query, search_fn(query, user_id, top_k * 2))
        for query in clean_queries
    ]
    return _rrf_merge(query_hits, top_k=top_k)


def multi_query_bm25(queries: list[str], user_id: UserFilter = None, top_k: int = 8) -> list[dict]:
    return multi_query(queries, user_id=user_id, top_k=top_k, search_fn=bm25)


def multi_query_llm_sparse_bm25(queries: list[str], user_id: UserFilter = None, top_k: int = 8) -> list[dict]:
    return multi_query(queries, user_id=user_id, top_k=top_k, search_fn=llm_sparse_bm25)


def multi_query_hybrid(queries: list[str], user_id: UserFilter = None, top_k: int = 8) -> list[dict]:
    return multi_query(queries, user_id=user_id, top_k=top_k, search_fn=hybrid_rrf)


BASELINES = {
    "bm25": bm25,
    "llm_sparse_bm25": llm_sparse_bm25,
    "dense": dense,
    "hybrid_rrf": hybrid_rrf,
    "multi_query_bm25": multi_query_bm25,
    "multi_query_llm_sparse_bm25": multi_query_llm_sparse_bm25,
    "multi_query_hybrid": multi_query_hybrid,
}
