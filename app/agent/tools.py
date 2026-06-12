# -*- coding: utf-8 -*-
"""工具定义（JSON schema）与执行函数。"""

import json
from typing import Optional
from app.storage.db import get_connection

# ---------- 工具 Schema ----------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_meetings",
            "description": (
                "通过语义+关键词混合检索，在会议转写原文中搜索相关片段。"
                "适用于查找具体讨论内容、某人的发言、背景信息等。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询词或自然语言问句"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_action_items",
            "description": (
                "获取结构化待办事项列表（含负责人、截止日期）。"
                "适用于'有哪些待办'、'谁负责什么任务'等问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "可选关键词过滤，如人名或项目名"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_decisions",
            "description": (
                "获取结构化决策记录。适用于'做了哪些决定'、'某项目怎么决策的'等问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "可选关键词过滤"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_risks",
            "description": (
                "获取结构化风险项列表。适用于'有哪些风险'、'存在什么问题'等问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "可选关键词过滤"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_meeting_summary",
            "description": (
                "获取某场会议的摘要、主题和要点。需要提供 note_id。"
                "不知道 note_id 时，先调用 list_meetings 查询。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "会议唯一ID"},
                },
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_meetings",
            "description": (
                "列出用户最近的会议清单（标题、时间、note_id）。"
                "适用于'最近开了哪些会'或需要查找特定会议 note_id 时。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回数量，默认10，最大50"},
                },
                "required": [],
            },
        },
    },
]


# ---------- 工具执行 ----------

def _fmt_rows(rows, fields) -> str:
    if not rows:
        return "（无记录）"
    lines = []
    for r in rows:
        parts = [f"{k}={r[k]}" for k in fields if r[k]]
        lines.append("• " + " | ".join(parts))
    return "\n".join(lines)


def execute_tool(name: str, arguments: dict, user_id: Optional[str]) -> str:
    if name == "search_meetings":
        return _tool_search_meetings(arguments.get("query", ""), user_id)
    if name == "get_action_items":
        return _tool_get_action_items(user_id, arguments.get("keyword"))
    if name == "get_decisions":
        return _tool_get_decisions(user_id, arguments.get("keyword"))
    if name == "get_risks":
        return _tool_get_risks(user_id, arguments.get("keyword"))
    if name == "get_meeting_summary":
        return _tool_get_meeting_summary(arguments.get("note_id", ""), user_id)
    if name == "list_meetings":
        return _tool_list_meetings(user_id, arguments.get("limit", 10))
    return f"未知工具: {name}"


def _tool_search_meetings(query: str, user_id: Optional[str]) -> str:
    try:
        from app.embed.vector_store import count
        if count() > 0:
            from app.search.hybrid import search as hybrid_search
            hits = hybrid_search(query, user_id=user_id, top_k=5)
        else:
            raise Exception("no vectors")
    except Exception:
        from app.search.bm25 import search as bm25_search
        hits = bm25_search(query, user_id=user_id, top_k=5)

    if not hits:
        return "未找到相关会议片段。"

    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(
            f"[片段{i}] 会议：{h.get('title', '')} | 时间：{h.get('create_time', '')} | "
            f"发言人：{h.get('speaker', '')}\n{h['text']}"
        )
    return "\n\n".join(parts)


def _tool_get_action_items(user_id: Optional[str], keyword: Optional[str]) -> str:
    conn = get_connection()
    sql = (
        "SELECT ai.content, ai.owner, ai.due, m.title, m.create_time "
        "FROM action_items ai JOIN meetings m ON ai.note_id = m.note_id"
    )
    params = []
    where = []
    if user_id:
        where.append("m.user_id = ?")
        params.append(user_id)
    if keyword:
        where.append("ai.content LIKE ?")
        params.append(f"%{keyword}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.create_time DESC LIMIT 50"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()

    if not rows:
        return "（无待办事项）"
    lines = []
    for r in rows:
        line = f"• {r['content']}"
        if r.get("owner"):
            line += f"  [负责人: {r['owner']}]"
        if r.get("due"):
            line += f"  [截止: {r['due']}]"
        line += f"  — 来自《{r['title']}》{r['create_time'][:10]}"
        lines.append(line)
    return f"共 {len(rows)} 条待办：\n" + "\n".join(lines)


def _tool_get_decisions(user_id: Optional[str], keyword: Optional[str]) -> str:
    conn = get_connection()
    sql = (
        "SELECT d.content, m.title, m.create_time "
        "FROM decisions d JOIN meetings m ON d.note_id = m.note_id"
    )
    params = []
    where = []
    if user_id:
        where.append("m.user_id = ?")
        params.append(user_id)
    if keyword:
        where.append("d.content LIKE ?")
        params.append(f"%{keyword}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.create_time DESC LIMIT 50"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()

    if not rows:
        return "（无决策记录）"
    lines = []
    for r in rows:
        lines.append(f"• {r['content']}  — 来自《{r['title']}》{r['create_time'][:10]}")
    return f"共 {len(rows)} 条决策：\n" + "\n".join(lines)


def _tool_get_risks(user_id: Optional[str], keyword: Optional[str]) -> str:
    conn = get_connection()
    sql = (
        "SELECT r.content, m.title, m.create_time "
        "FROM risks r JOIN meetings m ON r.note_id = m.note_id"
    )
    params = []
    where = []
    if user_id:
        where.append("m.user_id = ?")
        params.append(user_id)
    if keyword:
        where.append("r.content LIKE ?")
        params.append(f"%{keyword}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.create_time DESC LIMIT 50"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()

    if not rows:
        return "（无风险记录）"
    lines = []
    for r in rows:
        lines.append(f"• {r['content']}  — 来自《{r['title']}》{r['create_time'][:10]}")
    return f"共 {len(rows)} 条风险：\n" + "\n".join(lines)


def _tool_get_meeting_summary(note_id: str, user_id: Optional[str]) -> str:
    conn = get_connection()
    # 可选：校验 note_id 属于该 user
    if user_id:
        owner = conn.execute(
            "SELECT user_id FROM meetings WHERE note_id = ?", (note_id,)
        ).fetchone()
        if not owner or owner["user_id"] != user_id:
            conn.close()
            return f"未找到 note_id={note_id} 的会议（或无权限）。"

    row = conn.execute(
        "SELECT ms.summary, ms.topics, ms.key_points, m.title, m.create_time "
        "FROM meeting_summaries ms JOIN meetings m ON ms.note_id = m.note_id "
        "WHERE ms.note_id = ?",
        (note_id,),
    ).fetchone()
    conn.close()

    if not row:
        return f"会议 {note_id} 尚未做结构化摘要抽取。"

    row = dict(row)
    parts = [f"《{row['title']}》 {row['create_time'][:10]}"]
    if row.get("summary"):
        parts.append(f"\n摘要：{row['summary']}")
    if row.get("topics"):
        try:
            topics = json.loads(row["topics"])
            parts.append("主要议题：" + "、".join(topics))
        except Exception:
            pass
    if row.get("key_points"):
        try:
            kps = json.loads(row["key_points"])
            parts.append("核心要点：\n" + "\n".join(f"  • {p}" for p in kps))
        except Exception:
            pass
    return "\n".join(parts)


def _tool_list_meetings(user_id: Optional[str], limit: int) -> str:
    limit = min(int(limit), 50)
    conn = get_connection()
    sql = (
        "SELECT note_id, title, create_time, duration_minutes "
        "FROM meetings"
    )
    params = []
    if user_id:
        sql += " WHERE user_id = ?"
        params.append(user_id)
    sql += " ORDER BY create_time DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()

    if not rows:
        return "（无会议记录）"
    lines = []
    for r in rows:
        dur = f" {int(r['duration_minutes'])}分钟" if r.get("duration_minutes") else ""
        lines.append(f"• [{r['create_time'][:10]}]{dur} 《{r['title']}》  note_id={r['note_id']}")
    return f"共 {len(rows)} 场会议（最近优先）：\n" + "\n".join(lines)
