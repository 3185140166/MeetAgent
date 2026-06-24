# -*- coding: utf-8 -*-
"""Embedding 编码器，支持本地模型（bge-small）和 DashScope API 两种方案。

通过 EMBED_PROVIDER 环境变量切换：
  local      - 使用 sentence-transformers 加载 EMBED_LOCAL_MODEL
               如果 EMBED_LOCAL_MODEL 是本地路径，则只从该路径加载；
               如果是 HuggingFace 模型名，则可能联网下载/补齐到 EMBED_MODEL_DIR。
  dashscope  - 使用阿里云 DashScope API，不加载本地模型。
"""
from typing import List
from app.config import EMBED_PROVIDER, EMBED_LOCAL_MODEL, EMBED_MODEL_DIR, EMBED_DIM, EMBED_MAX_SEQ_LENGTH
from app.config import DASHSCOPE_BASE_URL, DASHSCOPE_API_KEY, DASHSCOPE_EMBEDDING_MODEL

_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        import os
        from pathlib import Path
        from app.config import PROJECT_ROOT
        from sentence_transformers import SentenceTransformer
        os.makedirs(EMBED_MODEL_DIR, exist_ok=True)
        model_path = Path(EMBED_LOCAL_MODEL)
        if not model_path.is_absolute() and (PROJECT_ROOT / model_path).exists():
            model_path = PROJECT_ROOT / model_path
        model_name_or_path = str(model_path) if model_path.exists() else EMBED_LOCAL_MODEL
        print(f"加载 Embedding 模型: {model_name_or_path}  缓存目录: {EMBED_MODEL_DIR}")
        _local_model = SentenceTransformer(
            model_name_or_path,
            cache_folder=EMBED_MODEL_DIR,
            trust_remote_code=True,
        )
        if EMBED_MAX_SEQ_LENGTH > 0:
            model_limit = int(getattr(_local_model, "max_seq_length", 0) or 0)
            if model_limit and EMBED_MAX_SEQ_LENGTH > model_limit:
                print(
                    f"EMBED_MAX_SEQ_LENGTH={EMBED_MAX_SEQ_LENGTH} exceeds model default "
                    f"{model_limit}; using {model_limit}"
                )
            else:
                _local_model.max_seq_length = EMBED_MAX_SEQ_LENGTH
                print(f"Embedding max_seq_length set to {_local_model.max_seq_length}")
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
