# -*- coding: utf-8 -*-
"""从结构化会议记忆生成少量 Long-term Memory。"""

import argparse
import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.memory.store import add_memory, search_memories, update_memory
from app.storage.db import get_connection, init_db


def _load_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _upsert_topic_memory(user_id: str | None, subject: str, content: str, evidence: list[dict]) -> dict:
    existing = search_memories(
        query=subject,
        user_id=user_id,
        scope="meeting_topic",
        memory_type="topic",
        limit=5,
    )
    for row in existing:
        if row.get("subject") == subject:
            return update_memory(
                row["memory_id"],
                content=content,
                evidence=evidence,
                source_type="extracted_meeting",
                trust_score=max(float(row.get("trust_score") or 0.7), 0.75),
            )
    return add_memory(
        user_id=user_id,
        scope="meeting_topic",
        memory_type="topic",
        subject=subject,
        content=content,
        trust_score=0.75,
        source_type="extracted_meeting",
        evidence=evidence,
    )


def build_meeting_memories(user_id: str | None = None, min_count: int = 2, limit: int = 50) -> int:
    conn = get_connection()
    params = []
    where = ""
    if user_id:
        where = "WHERE m.user_id = ?"
        params.append(user_id)
    rows = [dict(r) for r in conn.execute(
        f"""
        SELECT m.note_id, m.user_id, m.title, m.create_time, ms.summary, ms.topics
        FROM meeting_summaries ms
        JOIN meetings m ON m.note_id = ms.note_id
        {where}
        ORDER BY m.create_time ASC
        """,
        params,
    ).fetchall()]
    conn.close()

    groups: dict[tuple[str | None, str], list[dict]] = defaultdict(list)
    for row in rows:
        for topic in _load_json_list(row.get("topics")):
            topic = str(topic).strip()
            if topic:
                groups[(row.get("user_id"), topic)].append(row)

    saved = 0
    for (uid, topic), topic_rows in groups.items():
        if len(topic_rows) < min_count:
            continue
        topic_rows = topic_rows[:limit]
        first = (topic_rows[0].get("create_time") or "")[:10]
        last = (topic_rows[-1].get("create_time") or "")[:10]
        titles = "、".join((r.get("title") or "未命名会议") for r in topic_rows[:5])
        summaries = "；".join((r.get("summary") or "")[:120] for r in topic_rows[:4] if r.get("summary"))
        content = (
            f"主题“{topic}”在 {first} 至 {last} 的 {len(topic_rows)} 场会议中反复出现。"
            f"相关会议包括：{titles}。主要内容：{summaries}"
        )
        evidence = [
            {
                "note_id": r.get("note_id"),
                "title": r.get("title"),
                "create_time": r.get("create_time"),
            }
            for r in topic_rows
        ]
        _upsert_topic_memory(uid, topic, content, evidence)
        saved += 1
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从结构化会议摘要生成长期主题记忆")
    parser.add_argument("--user-id", type=str, default=None, help="只处理指定用户")
    parser.add_argument("--min-count", type=int, default=2, help="主题至少出现几场会议才沉淀，默认 2")
    parser.add_argument("--limit", type=int, default=50, help="每个主题最多引用会议数")
    args = parser.parse_args()

    init_db()
    count = build_meeting_memories(user_id=args.user_id, min_count=args.min_count, limit=args.limit)
    scope = f"用户 {args.user_id}" if args.user_id else "全部用户"
    print(f"{scope} 会议长期主题记忆构建完成：{count} 条")
