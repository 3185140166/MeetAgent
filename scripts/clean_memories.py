# -*- coding: utf-8 -*-
"""清理 Long-term Memory：过期标记 expired，低 trust 标记 deprecated。"""

import argparse
import io
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.memory.store import rebuild_fts, set_status
from app.storage.db import get_connection, init_db


def clean_memories(low_trust: float, older_than_days: int, dry_run: bool) -> dict:
    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=older_than_days)).strftime("%Y-%m-%d %H:%M:%S")
    today = now.strftime("%Y-%m-%d")

    conn = get_connection()
    expired = [dict(r) for r in conn.execute(
        """
        SELECT memory_id FROM memories
        WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at != '' AND expires_at <= ?
        """,
        (today,),
    ).fetchall()]
    low = [dict(r) for r in conn.execute(
        """
        SELECT memory_id FROM memories
        WHERE status = 'active' AND trust_score < ? AND updated_at <= ?
        """,
        (low_trust, cutoff),
    ).fetchall()]
    conn.close()

    if not dry_run:
        for row in expired:
            set_status(row["memory_id"], "expired")
        for row in low:
            set_status(row["memory_id"], "deprecated")
        rebuild_fts()

    return {
        "expired": len(expired),
        "deprecated_low_trust": len(low),
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理长期记忆")
    parser.add_argument("--low-trust", type=float, default=0.3, help="低于该 trust 的记忆会被废弃")
    parser.add_argument("--older-than-days", type=int, default=30, help="低 trust 记忆至少多久未更新才废弃")
    parser.add_argument("--dry-run", action="store_true", help="只查看数量，不实际修改")
    args = parser.parse_args()

    init_db()
    result = clean_memories(args.low_trust, args.older_than_days, args.dry_run)
    print(result)
