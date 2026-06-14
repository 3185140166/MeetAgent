# -*- coding: utf-8 -*-
"""查看或搜索长期记忆。"""

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.memory.store import list_memories, rebuild_fts, search_memories
from app.storage.db import init_db


def print_memory(memory: dict) -> None:
    subject = memory.get("subject") or "-"
    print(
        f"{memory['memory_id']}  [{memory['status']}] "
        f"{memory['scope']}/{memory['memory_type']}  {subject}  trust={memory['trust_score']}"
    )
    print(f"  user_id={memory.get('user_id') or '-'}  updated_at={memory.get('updated_at') or '-'}")
    print(f"  {memory['content']}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="查看或搜索长期记忆")
    parser.add_argument("--user-id", type=str, default=None, help="用户 ID")
    parser.add_argument("--query", type=str, default="", help="搜索关键词")
    parser.add_argument("--scope", type=str, default=None, help="user / project / meeting_topic")
    parser.add_argument("--type", type=str, default=None, help="preference / fact / task / topic / decision / risk")
    parser.add_argument("--include-inactive", action="store_true", help="包含 deprecated / deleted / expired")
    parser.add_argument("--limit", type=int, default=20, help="显示数量")
    parser.add_argument("--rebuild-fts", action="store_true", help="重建 memory_fts 后退出")
    args = parser.parse_args()

    init_db()

    if args.rebuild_fts:
        count = rebuild_fts()
        print(f"memory_fts 已重建：{count} 条 active memory")
        sys.exit(0)

    if args.query:
        rows = search_memories(
            query=args.query,
            user_id=args.user_id,
            include_inactive=args.include_inactive,
            scope=args.scope,
            memory_type=args.type,
            limit=args.limit,
        )
    else:
        rows = list_memories(
            user_id=args.user_id,
            include_inactive=args.include_inactive,
            limit=args.limit,
        )

    print(f"共 {len(rows)} 条\n")
    for memory in rows:
        print_memory(memory)
