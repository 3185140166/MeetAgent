# -*- coding: utf-8 -*-
"""结构化抽取 CLI。

用法:
    python -m app.extract.run --limit 5                          # 抽取 5 场尚未处理的会议
    python -m app.extract.run --user-id 1006734045 --limit 25   # 抽取指定用户的前 25 场
    python -m app.extract.run --limit 5 --force                 # 重抽取（含已处理的）
    python -m app.extract.run --note-id <id>                    # 抽取指定单场会议
"""
import sys
import io
import time
import asyncio
import argparse

from app.storage.db import get_connection, init_db
from app.extract.extractor import extract_meeting


def _pending_meetings(limit: int, force: bool, user_id: str = None):
    conn = get_connection()
    uid_filter = "AND m.user_id = ?" if user_id else ""
    params_base = [user_id] if user_id else []

    if force:
        rows = conn.execute(
            f"SELECT note_id, title FROM meetings WHERE 1=1 {uid_filter} "
            f"ORDER BY create_time ASC LIMIT ?",
            params_base + [limit],
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT m.note_id, m.title FROM meetings m
            LEFT JOIN meeting_summaries s ON s.note_id = m.note_id
            WHERE s.note_id IS NULL {uid_filter}
            ORDER BY m.create_time ASC
            LIMIT ?
            """,
            params_base + [limit],
        ).fetchall()
    conn.close()
    return rows


async def main(limit: int, force: bool, note_id: str = None, user_id: str = None):
    init_db()

    if note_id:
        conn = get_connection()
        row = conn.execute(
            "SELECT note_id, title FROM meetings WHERE note_id = ?", (note_id,)
        ).fetchone()
        conn.close()
        meetings = [row] if row else []
    else:
        meetings = _pending_meetings(limit, force, user_id)

    if not meetings:
        print("没有需要抽取的会议。")
        return

    print(f"待抽取会议数: {len(meetings)}\n")
    ok, fail = 0, 0
    for i, m in enumerate(meetings, 1):
        t0 = time.time()
        print(f"[{i}/{len(meetings)}] {m['title']} ({m['note_id'][:8]}) 抽取中...")
        try:
            success = await extract_meeting(m["note_id"], m["title"])
        except Exception as e:
            success = False
            print(f"  [error] {type(e).__name__}: {e}")
        dt = time.time() - t0
        if success:
            ok += 1
            print(f"  完成，用时 {dt:.1f}s")
        else:
            fail += 1
            print(f"  失败，用时 {dt:.1f}s")

    print(f"\n抽取完成：成功 {ok}，失败 {fail}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    parser = argparse.ArgumentParser(description="会议结构化记忆抽取")
    parser.add_argument("--limit", type=int, default=5, help="最多抽取场数")
    parser.add_argument("--force", action="store_true", help="重抽取（含已处理的）")
    parser.add_argument("--note-id", type=str, default=None, help="抽取指定单场会议")
    parser.add_argument("--user-id", type=str, default=None, help="只处理指定用户的会议")
    args = parser.parse_args()
    asyncio.run(main(args.limit, args.force, args.note_id, args.user_id))
