# -*- coding: utf-8 -*-
"""手动新增长期记忆，用于阶段二调试。"""

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.memory.store import add_memory
from app.storage.db import init_db


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="手动新增长期记忆")
    parser.add_argument("content", help="记忆内容，建议写成事实陈述")
    parser.add_argument("--user-id", type=str, default=None, help="用户 ID")
    parser.add_argument("--scope", type=str, default="user", help="user / project / meeting_topic")
    parser.add_argument("--type", type=str, default="fact", help="preference / fact / task / topic / decision / risk")
    parser.add_argument("--subject", type=str, default="", help="主题，如 response_style / MeetAgent")
    parser.add_argument("--trust", type=float, default=0.7, help="可信度，默认 0.7")
    parser.add_argument("--source-type", type=str, default="manual", help="来源类型，默认 manual")
    parser.add_argument("--source-id", type=str, default="", help="来源 ID")
    parser.add_argument("--expires-at", type=str, default="", help="过期时间，可空")
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
    print(f"已新增 memory: {memory['memory_id']}")
    print(f"[{memory['scope']}/{memory['memory_type']}] {memory.get('subject') or '-'}")
    print(memory["content"])
