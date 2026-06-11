# -*- coding: utf-8 -*-
"""ChromaDB 向量存储封装。

持久化路径：data/chroma/
Collection：meet_chunks
文档 ID：chunk_id（与 SQLite chunks 表对应）
Metadata：chunk_id, note_id, user_id（用于过滤）
"""
from typing import List, Dict, Optional
import os
import chromadb
from app.config import DB_PATH

_COLLECTION_NAME = "meet_chunks"
_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        chroma_path = os.path.join(os.path.dirname(DB_PATH), "chroma")
        os.makedirs(chroma_path, exist_ok=True)
        _client = chromadb.PersistentClient(path=chroma_path)
        _collection = _client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def upsert(chunk_id: str, note_id: str, user_id: str, text: str, embedding: List[float]) -> None:
    col = _get_collection()
    col.upsert(
        ids=[chunk_id],
        embeddings=[embedding],
        documents=[text],
        metadatas=[{"chunk_id": chunk_id, "note_id": note_id, "user_id": user_id}],
    )


def upsert_batch(
    chunk_ids: List[str],
    note_ids: List[str],
    user_ids: List[str],
    texts: List[str],
    embeddings: List[List[float]],
) -> None:
    col = _get_collection()
    col.upsert(
        ids=chunk_ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=[
            {"chunk_id": cid, "note_id": nid, "user_id": uid}
            for cid, nid, uid in zip(chunk_ids, note_ids, user_ids)
        ],
    )


def search(
    query_embedding: List[float],
    user_id: Optional[str] = None,
    top_k: int = 8,
) -> List[Dict]:
    """向量相似度检索，返回格式与 BM25 search 一致。"""
    col = _get_collection()
    where = {"user_id": user_id} if user_id else None
    results = col.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["metadatas", "documents", "distances"],
    )

    hits = []
    for i, chunk_id in enumerate(results["ids"][0]):
        meta = results["metadatas"][0][i]
        distance = results["distances"][0][i]
        hits.append({
            "chunk_id": chunk_id,
            "note_id": meta["note_id"],
            "user_id": meta["user_id"],
            "score": 1 - distance,   # cosine distance → similarity
            "text": results["documents"][0][i],
        })
    return hits


def count() -> int:
    return _get_collection().count()
