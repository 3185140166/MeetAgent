# -*- coding: utf-8 -*-
"""Manually add one long-term memory."""

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.memory.store import add_memory
from app.storage.db import init_db


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add one preference or reflection memory")
    parser.add_argument("content", help="Memory content")
    parser.add_argument("--user-id", type=str, default=None, help="User ID")
    parser.add_argument("--scope", type=str, default="user", help="user / project / meeting_topic")
    parser.add_argument("--type", type=str, default="preference", help="preference / reflection")
    parser.add_argument("--subject", type=str, default="user_profile", help="user_profile or reflection subject")
    parser.add_argument("--trust", type=float, default=0.7, help="Trust score")
    parser.add_argument("--source-type", type=str, default="manual", help="Source type")
    parser.add_argument("--source-id", type=str, default="", help="Source ID")
    parser.add_argument("--expires-at", type=str, default="", help="Expiration time")
    args = parser.parse_args()

    init_db()
    memory = add_memory(
        user_id=args.user_id,
        content=args.content,
        scope=args.scope,
        memory_type=args.type,
        subject=args.subject,
        trust_score=args.trust,
        source_type=args.source_type,
        source_id=args.source_id,
        expires_at=args.expires_at,
    )
    print(f"added memory: {memory['memory_id']}")
    print(f"[{memory['scope']}/{memory['memory_type']}] {memory.get('subject') or '-'}")
    print(memory["content"])
