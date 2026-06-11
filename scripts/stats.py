# -*- coding: utf-8 -*-
"""
查看数据库整体统计信息。

输出内容：
- 每个用户的会议数、总字数、时间跨度
- 每个用户的结构化抽取进度（已抽取 / 未抽取）

用法：
    python scripts/stats.py
"""
import sys
import io
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.storage.db import get_connection


def main():
    conn = get_connection()

    # 总览
    total_meetings = conn.execute("SELECT COUNT(*) FROM meetings").fetchone()[0]
    total_chunks   = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    total_extracted = conn.execute("SELECT COUNT(*) FROM meeting_summaries").fetchone()[0]

    print("=" * 70)
    print(f"  会议总数: {total_meetings}  |  chunks 总数: {total_chunks}  |  已抽取: {total_extracted}")
    print("=" * 70)

    # 按用户
    rows = conn.execute("""
        SELECT
            m.user_id,
            COUNT(DISTINCT m.note_id)         AS n_meetings,
            COUNT(DISTINCT s.note_id)         AS n_extracted,
            SUM(m.asr_result_length)          AS total_chars,
            MIN(m.create_time)                AS earliest,
            MAX(m.create_time)                AS latest
        FROM meetings m
        LEFT JOIN meeting_summaries s ON s.note_id = m.note_id
        GROUP BY m.user_id
        ORDER BY n_meetings DESC
    """).fetchall()

    print(f"\n{'user_id':<15} {'会议':>4} {'已抽取':>6} {'进度':>6} {'总字数':>10}  时间跨度")
    print("-" * 70)
    for r in rows:
        pct = f"{r['n_extracted']/r['n_meetings']*100:.0f}%" if r['n_meetings'] else "-"
        chars = r['total_chars'] or 0
        span = f"{r['earliest'][:10]} ~ {r['latest'][:10]}"
        print(f"{r['user_id']:<15} {r['n_meetings']:>4} {r['n_extracted']:>6} {pct:>6} {chars:>10,}  {span}")

    conn.close()


if __name__ == "__main__":
    main()
