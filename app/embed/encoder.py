# -*- coding: utf-8 -*-
"""Embedding 编码器，支持本地模型（bge-small）和 DashScope API 两种方案。

通过 EMBED_PROVIDER 环境变量切换：
  local      - 使用 sentence-transformers 加载本地/HuggingFace 模型（默认）
  dashscope  - 使用阿里云 DashScope API
"""
from typing import List
from app.config import EMBED_PROVIDER, EMBED_LOCAL_MODEL, EMBED_MODEL_DIR, EMBED_DIM
from app.config import DASHSCOPE_BASE_URL, DASHSCOPE_API_KEY, DASHSCOPE_EMBEDDING_MODEL

_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        import os
        from sentence_transformers import SentenceTransformer
        os.makedirs(EMBED_MODEL_DIR, exist_ok=True)
        print(f"加载 Embedding 模型: {EMBED_LOCAL_MODEL}  缓存目录: {EMBED_MODEL_DIR}")
        _local_model = SentenceTransformer(EMBED_LOCAL_MODEL, cache_folder=EMBED_MODEL_DIR)
        print("模型加载完成")
    return _local_model


def _embed_local(texts: List[str]) -> List[List[float]]:
    model = _get_local_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vecs.tolist()


def _embed_dashscope(texts: List[str]) -> List[List[float]]:
    import httpx, json
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    # DashScope 每次最多 25 条，分批处理
    results = []
    batch_size = 25
    for i in range(0, len(texts), batch_size):
        batch = texts[i: i + batch_size]
        payload = {"model": DASHSCOPE_EMBEDDING_MODEL, "input": batch}
        resp = httpx.post(
            f"{DASHSCOPE_BASE_URL}/embeddings",
            json=payload,
            headers=headers,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results.extend([item["embedding"] for item in data["data"]])
    return results


def embed(texts: List[str]) -> List[List[float]]:
    """将文本列表编码为向量列表。"""
    if not texts:
        return []
    if EMBED_PROVIDER == "dashscope":
        return _embed_dashscope(texts)
    return _embed_local(texts)


def embed_one(text: str) -> List[float]:
    return embed([text])[0]
