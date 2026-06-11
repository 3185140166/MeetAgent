# -*- coding: utf-8 -*-
"""混合检索：BM25 关键词召回 + 向量语义召回，通过 RRF 融合排序。

RRF (Reciprocal Rank Fusion)：score = Σ 1 / (k + rank)，k=60 是经验常数。
两路各取 top_k * 2，融合后返回 top_k 个结果。
"""
from typing import List, Dict, Optional
from app.search.bm25 import search as bm25_search
from app.embed.encoder import embed_one
from app.embed.vector_store import search as vec_search
from app.storage.db import get_connection
from app.config import TOP_K

_RRF_K = 60


def _rrf_merge(bm25_hits: List[Dict], vec_hits: List[Dict], top_k: int) -> List[Dict]:
    scores: Dict[str, float] = {}
    sources: Dict[str, Dict] = {}

    for rank, hit in enumerate(bm25_hits):
        cid = hit["chunk_id"]
        scores[cid] = scores.get(cid, 0) + 1 / (_RRF_K + rank + 1)
        sources[cid] = hit

    for rank, hit in enumerate(vec_hits):
        cid = hit["chunk_id"]
        scores[cid] = scores.get(cid, 0) + 1 / (_RRF_K + rank + 1)
        if cid not in sources:
            sources[cid] = hit

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    # 补充 SQLite 里的 title / create_time / speaker 字段
    conn = get_connection()
    result = []
    for chunk_id, rrf_score in ranked:
        hit = dict(sources[chunk_id])
        if "title" not in hit:
            row = conn.execute("""
                SELECT c.speaker, c.chunk_index, c.text, m.title, m.create_time
                FROM chunks c JOIN meetings m ON m.note_id = c.note_id
                WHERE c.chunk_id = ?
            """, (chunk_id,)).fetchone()
            if row:
                hit.update(dict(row))
        hit["rrf_score"] = rrf_score
        result.append(hit)
    conn.close()
    return result


def search(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = TOP_K,
) -> List[Dict]:
    fetch_k = top_k * 2

    bm25_hits = bm25_search(query, user_id=user_id, top_k=fetch_k)
    query_vec = embed_one(query)
    vec_hits = vec_search(query_vec, user_id=user_id, top_k=fetch_k)

    return _rrf_merge(bm25_hits, vec_hits, top_k)
