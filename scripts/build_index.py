# -*- coding: utf-8 -*-
"""
构建向量索引：读取 SQLite chunks 表，用 Embedding 模型编码后写入 ChromaDB。

首次运行会自动下载 bge-small-zh-v1.5 模型（~90MB）。
重复运行安全（upsert），可用于增量更新。

用法：
    # 对全部 chunks 建索引（首次）
    python scripts/build_index.py

    # 只对指定用户的 chunks 建索引
    python scripts/build_index.py --user-id 1006734045

    # 调整批大小（CPU 内存紧张时可调小）
    python scripts/build_index.py --batch-size 64
"""
import sys
import io
import os
import argparse
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.storage.db import get_connection
from app.embed.encoder import embed
from app.embed.vector_store import upsert_batch, count


def build(user_id: str = None, batch_size: int = 128):
    conn = get_connection()

    if user_id:
        rows = conn.execute(
            "SELECT chunk_id, note_id, user_id, text FROM chunks WHERE user_id = ? ORDER BY chunk_id",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT chunk_id, note_id, user_id, text FROM chunks ORDER BY chunk_id"
        ).fetchall()
    conn.close()

    total = len(rows)
    print(f"待编码 chunks: {total}  批大小: {batch_size}\n")

    t0 = time.time()
    for start in range(0, total, batch_size):
        batch = rows[start: start + batch_size]
        texts = [r["text"] for r in batch]
        embeddings = embed(texts)
        upsert_batch(
            chunk_ids=[r["chunk_id"] for r in batch],
            note_ids=[r["note_id"] for r in batch],
            user_ids=[r["user_id"] for r in batch],
            texts=texts,
            embeddings=embeddings,
        )
        done = min(start + batch_size, total)
        elapsed = time.time() - t0
        speed = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / speed if speed > 0 else 0
        print(f"  [{done}/{total}] 已完成 {done/total*100:.1f}%  速度 {speed:.1f} chunks/s  预计剩余 {eta:.0f}s")

    print(f"\n完成！共 {total} 条，用时 {time.time()-t0:.1f}s")
    print(f"ChromaDB 当前总索引量: {count()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建向量索引")
    parser.add_argument("--user-id", type=str, default=None, help="只对指定用户建索引")
    parser.add_argument("--batch-size", type=int, default=128, help="每批编码数量（默认 128）")
    args = parser.parse_args()
    build(args.user_id, args.batch_size)
