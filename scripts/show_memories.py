# -*- coding: utf-8 -*-
"""List or search long-term memories."""

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
    parser = argparse.ArgumentParser(description="List or search long-term memories")
    parser.add_argument("--user-id", type=str, default=None, help="User ID")
    parser.add_argument("--query", type=str, default="", help="Search query")
    parser.add_argument("--scope", type=str, default=None, help="user / project / meeting_topic")
    parser.add_argument("--type", type=str, default=None, help="preference / reflection")
    parser.add_argument("--include-inactive", action="store_true", help="Include inactive memories")
    parser.add_argument("--limit", type=int, default=20, help="Limit")
    parser.add_argument("--rebuild-fts", action="store_true", help="Rebuild memory_fts then exit")
    args = parser.parse_args()

    init_db()

    if args.rebuild_fts:
        count = rebuild_fts()
        print(f"rebuilt memory_fts: {count} active memories")
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

    print(f"total {len(rows)}\n")
    for memory in rows:
        print_memory(memory)
