# -*- coding: utf-8 -*-
"""
查看指定用户或会议的结构化记忆内容。

用法：
    # 查看某用户所有已抽取会议的摘要列表
    python scripts/show_memory.py --user-id 1006734045

    # 查看某场会议的完整结构化记忆
    python scripts/show_memory.py --note-id <note_id>

    # 只看某类数据
    python scripts/show_memory.py --user-id 1006734045 --type action_items
    python scripts/show_memory.py --user-id 1006734045 --type decisions
    python scripts/show_memory.py --user-id 1006734045 --type risks
    python scripts/show_memory.py --user-id 1006734045 --type entities
"""
import sys
import io
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.storage.db import get_connection


def show_summaries(conn, user_id: str):
    rows = conn.execute("""
        SELECT m.note_id, m.title, m.create_time, s.summary
        FROM meeting_summaries s JOIN meetings m ON m.note_id = s.note_id
        WHERE m.user_id = ?
        ORDER BY m.create_time ASC
    """, (user_id,)).fetchall()
    print(f"用户 {user_id} 已抽取会议（{len(rows)} 场）\n")
    for r in rows:
        print(f"  [{r['create_time'][:10]}] {r['title']}")
        print(f"    {r['summary'][:80]}...")
        print()


def show_meeting(conn, note_id: str):
    m = conn.execute("SELECT * FROM meetings WHERE note_id = ?", (note_id,)).fetchone()
    s = conn.execute("SELECT * FROM meeting_summaries WHERE note_id = ?", (note_id,)).fetchone()
    if not s:
        print(f"会议 {note_id} 尚未抽取。")
        return

    import json
    print(f"=== {m['title']}  {m['create_time']} ===\n")
    print(f"【摘要】\n{s['summary']}\n")
    print(f"【议题】")
    for t in json.loads(s['topics'] or '[]'):
        print(f"  · {t}")

    for table, label in [("action_items", "待办"), ("decisions", "决策"), ("risks", "风险")]:
        rows = conn.execute(f"SELECT * FROM {table} WHERE note_id = ?", (note_id,)).fetchall()
        print(f"\n【{label} {len(rows)} 条】")
        for r in rows:
            line = f"  - {r['content']}"
            if table == "action_items" and r['owner']:
                line += f"  （{r['owner']}）"
            print(line)

    ents = conn.execute(
        "SELECT entity_type, name FROM entities WHERE note_id = ? ORDER BY entity_type, name",
        (note_id,)
    ).fetchall()
    print(f"\n【实体 {len(ents)} 个】")
    for e in ents:
        print(f"  [{e['entity_type']}] {e['name']}")


def show_type(conn, user_id: str, data_type: str):
    table_map = {
        "action_items": ("action_items", "content", "待办"),
        "decisions":    ("decisions",    "content", "决策"),
        "risks":        ("risks",        "content", "风险"),
        "entities":     ("entities",     "name",    "实体"),
    }
    if data_type not in table_map:
        print(f"--type 只支持: {', '.join(table_map)}")
        return
    table, col, label = table_map[data_type]
    rows = conn.execute(f"""
        SELECT t.*, m.title, m.create_time FROM {table} t
        JOIN meetings m ON m.note_id = t.note_id
        WHERE m.user_id = ?
        ORDER BY m.create_time ASC
    """, (user_id,)).fetchall()
    print(f"用户 {user_id} — {label}（共 {len(rows)} 条）\n")
    for r in rows:
        prefix = f"[{r['create_time'][:10]}] {r['title'][:20]}"
        if data_type == "entities":
            print(f"  {prefix}  [{r['entity_type']}] {r['name']}")
        else:
            print(f"  {prefix}  {r[col]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="查看结构化会议记忆")
    parser.add_argument("--user-id", type=str, help="用户 ID")
    parser.add_argument("--note-id", type=str, help="查看指定会议的完整记忆")
    parser.add_argument("--type", type=str, help="筛选类型: action_items / decisions / risks / entities")
    args = parser.parse_args()

    conn = get_connection()
    if args.note_id:
        show_meeting(conn, args.note_id)
    elif args.user_id and args.type:
        show_type(conn, args.user_id, args.type)
    elif args.user_id:
        show_summaries(conn, args.user_id)
    else:
        print("请指定 --user-id 或 --note-id")
    conn.close()
