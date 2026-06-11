# -*- coding: utf-8 -*-
"""
对指定用户的会议做结构化记忆抽取。

典型工作流：
    1. 先用 stats.py 确认用户 ID 和会议数
    2. 用本脚本抽取"前 N 场"作为初始记忆，剩余留给增量测试
    3. 后续新会议进来时重新执行，已抽取的会议会自动跳过

用法：
    # 抽取用户 1006734045 的前 25 场（按时间升序）
    python scripts/extract_user.py --user-id 1006734045 --limit 25

    # 查看该用户还有多少未抽取
    python scripts/extract_user.py --user-id 1006734045 --dry-run

    # 强制重新抽取（会覆盖已有结果）
    python scripts/extract_user.py --user-id 1006734045 --limit 25 --force

注意：
    - 默认按 create_time 升序，即先处理最早的会议
    - 大场会议（>5万字）每场约需 2~3 分钟，请耐心等待
    - 抽取结果写入 meeting_summaries / action_items / decisions / risks / entities 表
"""
import sys
import io
import os
import asyncio
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.storage.db import get_connection, init_db
from app.extract.run import main as extract_main


def dry_run(user_id: str):
    conn = get_connection()
    total = conn.execute(
        "SELECT COUNT(*) FROM meetings WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    extracted = conn.execute(
        "SELECT COUNT(*) FROM meeting_summaries s "
        "JOIN meetings m ON m.note_id = s.note_id WHERE m.user_id = ?",
        (user_id,),
    ).fetchone()[0]
    pending = total - extracted
    conn.close()
    print(f"用户 {user_id}：共 {total} 场，已抽取 {extracted} 场，待处理 {pending} 场")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="对指定用户的会议做结构化记忆抽取")
    parser.add_argument("--user-id", required=True, help="用户 ID")
    parser.add_argument("--limit", type=int, default=10, help="本次最多抽取场数（默认 10）")
    parser.add_argument("--force", action="store_true", help="强制重抽取，覆盖已有结果")
    parser.add_argument("--dry-run", action="store_true", help="只查看待处理数量，不执行抽取")
    args = parser.parse_args()

    init_db()

    if args.dry_run:
        dry_run(args.user_id)
    else:
        asyncio.run(extract_main(
            limit=args.limit,
            force=args.force,
            note_id=None,
            user_id=args.user_id,
        ))
