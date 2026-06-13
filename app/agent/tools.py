# -*- coding: utf-8 -*-
"""工具定义（JSON schema）与执行函数。"""

import json
from typing import Optional
from app.config import ENABLE_HYBRID_SEARCH
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
    {
        "type": "function",
        "function": {
            "name": "get_meeting_detail",
            "description": (
                "获取某场会议的详情，包括会议元信息、摘要、待办、决策、风险和部分原文片段。"
                "适用于用户已经指定某场会议或 note_id，需要深入查看该会议内容时。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "会议唯一ID"},
                    "chunk_limit": {"type": "integer", "description": "返回原文片段数量，默认5，最大20"},
                },
                "required": ["note_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_time_range",
            "description": (
                "按时间范围搜索会议内容。适用于'上周'、'最近一个月'、'某段时间讨论了什么'等问题。"
                "时间格式使用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要搜索的主题或关键词，可为空"},
                    "start": {"type": "string", "description": "开始时间，如 2026-06-01"},
                    "end": {"type": "string", "description": "结束时间，如 2026-06-13"},
                    "limit": {"type": "integer", "description": "返回数量，默认10，最大30"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_topic_history",
            "description": (
                "梳理某个主题、项目、客户、产品或问题在历史会议中的讨论记录。"
                "适用于'这个问题之前怎么讨论的'、'某项目历史进展'等问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "要追踪的主题、项目、客户、产品或关键词"},
                    "limit": {"type": "integer", "description": "返回会议/片段数量，默认10，最大30"},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_weekly_report",
            "description": (
                "基于指定时间范围内的结构化会议记忆生成周报素材，汇总摘要、待办、决策和风险。"
                "适用于'生成本周周报'、'这周做了什么'等问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "开始日期，如 2026-06-08"},
                    "end": {"type": "string", "description": "结束日期，如 2026-06-14"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "联网搜索会议库之外的外部信息。适用于用户明确要求联网搜索、查询最新信息、"
                "或需要补充外部公司/产品/技术/政策背景时。不要用它替代本地会议检索。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "联网搜索关键词或自然语言查询"},
                    "max_results": {"type": "integer", "description": "返回结果数量，默认5，最大10"},
                },
                "required": ["query"],
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
    if name == "get_meeting_detail":
        return _tool_get_meeting_detail(
            arguments.get("note_id", ""),
            user_id,
            arguments.get("chunk_limit", 5),
        )
    if name == "search_by_time_range":
        return _tool_search_by_time_range(
            user_id=user_id,
            query=arguments.get("query", ""),
            start=arguments.get("start"),
            end=arguments.get("end"),
            limit=arguments.get("limit", 10),
        )
    if name == "get_topic_history":
        return _tool_get_topic_history(
            user_id=user_id,
            topic=arguments.get("topic", ""),
            limit=arguments.get("limit", 10),
        )
    if name == "generate_weekly_report":
        return _tool_generate_weekly_report(
            user_id=user_id,
            start=arguments.get("start"),
            end=arguments.get("end"),
        )
    if name == "web_search":
        return _tool_web_search(
            query=arguments.get("query", ""),
            max_results=arguments.get("max_results"),
        )
    return f"未知工具: {name}"


def _safe_limit(value, default: int, maximum: int) -> int:
    try:
        return min(max(int(value), 1), maximum)
    except Exception:
        return default


def _date_filter_sql(alias: str, start: Optional[str], end: Optional[str], params: list) -> list[str]:
    where = []
    if start:
        where.append(f"{alias}.create_time >= ?")
        params.append(start)
    if end:
        where.append(f"{alias}.create_time <= ?")
        params.append(end)
    return where


def _fmt_meeting_ref(row: dict) -> str:
    title = row.get("title") or "未命名会议"
    create_time = (row.get("create_time") or "")[:10]
    return f"《{title}》{create_time}"


def _tool_web_search(query: str, max_results=None) -> str:
    try:
        from app.agent.web_search import format_web_results, search_web
        results = search_web(query, max_results=max_results)
        return format_web_results(results)
    except Exception as e:
        return f"联网搜索失败：{type(e).__name__}: {e}"


def _tool_search_meetings(query: str, user_id: Optional[str]) -> str:
    if ENABLE_HYBRID_SEARCH:
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
    else:
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


def _tool_get_meeting_detail(note_id: str, user_id: Optional[str], chunk_limit: int) -> str:
    chunk_limit = _safe_limit(chunk_limit, 5, 20)
    conn = get_connection()
    params = [note_id]
    owner_filter = ""
    if user_id:
        owner_filter = " AND user_id = ?"
        params.append(user_id)

    meeting = conn.execute(
        f"SELECT * FROM meetings WHERE note_id = ?{owner_filter}",
        params,
    ).fetchone()
    if not meeting:
        conn.close()
        return f"未找到 note_id={note_id} 的会议（或无权限）。"

    meeting = dict(meeting)
    summary = conn.execute(
        "SELECT summary, topics, key_points FROM meeting_summaries WHERE note_id = ?",
        (note_id,),
    ).fetchone()
    action_items = [dict(r) for r in conn.execute(
        "SELECT content, owner, due FROM action_items WHERE note_id = ? ORDER BY id LIMIT 20",
        (note_id,),
    ).fetchall()]
    decisions = [dict(r) for r in conn.execute(
        "SELECT content FROM decisions WHERE note_id = ? ORDER BY id LIMIT 20",
        (note_id,),
    ).fetchall()]
    risks = [dict(r) for r in conn.execute(
        "SELECT content FROM risks WHERE note_id = ? ORDER BY id LIMIT 20",
        (note_id,),
    ).fetchall()]
    chunks = [dict(r) for r in conn.execute(
        "SELECT chunk_index, speaker, text FROM chunks WHERE note_id = ? ORDER BY chunk_index LIMIT ?",
        (note_id, chunk_limit),
    ).fetchall()]
    conn.close()

    parts = [
        f"会议详情：{_fmt_meeting_ref(meeting)}",
        f"note_id={meeting['note_id']} | user_id={meeting.get('user_id') or ''} | 时长={meeting.get('duration_minutes') or ''}分钟",
    ]

    if summary:
        summary = dict(summary)
        if summary.get("summary"):
            parts.append(f"\n摘要：{summary['summary']}")
        if summary.get("topics"):
            try:
                parts.append("主题：" + "、".join(json.loads(summary["topics"])))
            except Exception:
                pass
        if summary.get("key_points"):
            try:
                parts.append("要点：\n" + "\n".join(f"  • {p}" for p in json.loads(summary["key_points"])))
            except Exception:
                pass
    else:
        parts.append("\n该会议尚未做结构化摘要抽取。")

    if action_items:
        parts.append("\n待办：\n" + "\n".join(
            f"  • {r['content']}"
            + (f" [负责人: {r['owner']}]" if r.get("owner") else "")
            + (f" [截止: {r['due']}]" if r.get("due") else "")
            for r in action_items
        ))
    if decisions:
        parts.append("\n决策：\n" + "\n".join(f"  • {r['content']}" for r in decisions))
    if risks:
        parts.append("\n风险：\n" + "\n".join(f"  • {r['content']}" for r in risks))
    if chunks:
        parts.append("\n原文片段：\n" + "\n\n".join(
            f"[chunk#{r['chunk_index']} 发言人:{r.get('speaker') or ''}]\n{r['text'][:800]}"
            for r in chunks
        ))

    return "\n".join(parts)


def _tool_search_by_time_range(
    user_id: Optional[str],
    query: str,
    start: Optional[str],
    end: Optional[str],
    limit: int,
) -> str:
    limit = _safe_limit(limit, 10, 30)
    query = (query or "").strip()
    conn = get_connection()
    params = []
    where = []
    if user_id:
        where.append("m.user_id = ?")
        params.append(user_id)
    where.extend(_date_filter_sql("m", start, end, params))
    if query:
        like = f"%{query}%"
        where.append("(m.title LIKE ? OR c.text LIKE ?)")
        params.extend([like, like])
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    params.append(limit)

    rows = [dict(r) for r in conn.execute(
        f"""
        SELECT
          m.note_id,
          m.title,
          m.create_time,
          c.chunk_index,
          c.speaker,
          c.text
        FROM meetings m
        JOIN chunks c ON c.note_id = m.note_id
        {where_sql}
        ORDER BY m.create_time DESC, c.chunk_index ASC
        LIMIT ?
        """,
        params,
    ).fetchall()]
    conn.close()

    if not rows:
        return "该时间范围内未找到相关会议内容。"

    range_text = f"{start or '最早'} 至 {end or '最新'}"
    lines = [f"时间范围：{range_text}，共找到 {len(rows)} 条相关片段："]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"\n[片段{i}] {_fmt_meeting_ref(r)} | chunk#{r['chunk_index']} | 发言人:{r.get('speaker') or ''}\n"
            f"{r['text'][:700]}"
        )
    return "\n".join(lines)


def _tool_get_topic_history(user_id: Optional[str], topic: str, limit: int) -> str:
    topic = (topic or "").strip()
    if not topic:
        return "请提供要追踪的主题或关键词。"
    limit = _safe_limit(limit, 10, 30)
    like = f"%{topic}%"

    conn = get_connection()
    params = []
    user_filter = ""
    if user_id:
        user_filter = "AND m.user_id = ?"
        params.append(user_id)

    rows = [dict(r) for r in conn.execute(
        f"""
        SELECT
          m.note_id,
          m.title,
          m.create_time,
          c.chunk_index,
          c.speaker,
          c.text
        FROM chunks c
        JOIN meetings m ON m.note_id = c.note_id
        WHERE c.text LIKE ?
        {user_filter}
        ORDER BY m.create_time ASC, c.chunk_index ASC
        LIMIT ?
        """,
        [like] + params + [limit],
    ).fetchall()]

    memories = [dict(r) for r in conn.execute(
        f"""
        SELECT 'summary' AS type, m.title, m.create_time, ms.summary AS content
        FROM meeting_summaries ms JOIN meetings m ON m.note_id = ms.note_id
        WHERE ms.summary LIKE ? {user_filter}
        UNION ALL
        SELECT 'decision' AS type, m.title, m.create_time, d.content
        FROM decisions d JOIN meetings m ON m.note_id = d.note_id
        WHERE d.content LIKE ? {user_filter}
        UNION ALL
        SELECT 'risk' AS type, m.title, m.create_time, r.content
        FROM risks r JOIN meetings m ON m.note_id = r.note_id
        WHERE r.content LIKE ? {user_filter}
        ORDER BY create_time ASC
        LIMIT ?
        """,
        ([like] + params + [like] + params + [like] + params + [limit]),
    ).fetchall()]
    conn.close()

    if not rows and not memories:
        return f"未找到主题“{topic}”的历史讨论记录。"

    parts = [f"主题“{topic}”的历史记录："]
    if memories:
        parts.append("\n结构化记忆：")
        for r in memories:
            parts.append(f"  • [{r['type']}] {_fmt_meeting_ref(r)}：{r['content']}")
    if rows:
        parts.append("\n原文片段（按时间升序）：")
        for i, r in enumerate(rows, 1):
            parts.append(
                f"\n[片段{i}] {_fmt_meeting_ref(r)} | chunk#{r['chunk_index']} | 发言人:{r.get('speaker') or ''}\n"
                f"{r['text'][:700]}"
            )
    return "\n".join(parts)


def _tool_generate_weekly_report(
    user_id: Optional[str],
    start: Optional[str],
    end: Optional[str],
) -> str:
    conn = get_connection()
    params = []
    where = []
    if user_id:
        where.append("m.user_id = ?")
        params.append(user_id)
    where.extend(_date_filter_sql("m", start, end, params))
    where_sql = " WHERE " + " AND ".join(where) if where else ""

    meetings = [dict(r) for r in conn.execute(
        f"""
        SELECT m.note_id, m.title, m.create_time, ms.summary
        FROM meetings m
        LEFT JOIN meeting_summaries ms ON ms.note_id = m.note_id
        {where_sql}
        ORDER BY m.create_time ASC
        LIMIT 50
        """,
        params,
    ).fetchall()]

    def load_items(table: str) -> list[dict]:
        return [dict(r) for r in conn.execute(
            f"""
            SELECT t.content, m.title, m.create_time
            FROM {table} t JOIN meetings m ON m.note_id = t.note_id
            {where_sql}
            ORDER BY m.create_time ASC
            LIMIT 50
            """,
            params,
        ).fetchall()]

    action_items = [dict(r) for r in conn.execute(
        f"""
        SELECT ai.content, ai.owner, ai.due, m.title, m.create_time
        FROM action_items ai JOIN meetings m ON m.note_id = ai.note_id
        {where_sql}
        ORDER BY m.create_time ASC
        LIMIT 50
        """,
        params,
    ).fetchall()]
    decisions = load_items("decisions")
    risks = load_items("risks")
    conn.close()

    if not meetings:
        return "该时间范围内没有会议记录，无法生成周报素材。"

    range_text = f"{start or '最早'} 至 {end or '最新'}"
    parts = [
        f"周报素材（{range_text}）",
        f"会议数量：{len(meetings)}",
    ]
    parts.append("\n会议摘要：")
    for m in meetings:
        summary = m.get("summary") or "尚未抽取摘要"
        parts.append(f"  • {_fmt_meeting_ref(m)}：{summary}")

    if decisions:
        parts.append("\n关键决策：")
        parts.extend(f"  • {r['content']} — {_fmt_meeting_ref(r)}" for r in decisions)
    if action_items:
        parts.append("\n待办事项：")
        for r in action_items:
            line = f"  • {r['content']}"
            if r.get("owner"):
                line += f" [负责人: {r['owner']}]"
            if r.get("due"):
                line += f" [截止: {r['due']}]"
            line += f" — {_fmt_meeting_ref(r)}"
            parts.append(line)
    if risks:
        parts.append("\n风险与问题：")
        parts.extend(f"  • {r['content']} — {_fmt_meeting_ref(r)}" for r in risks)

    return "\n".join(parts)
