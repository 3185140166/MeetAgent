# -*- coding: utf-8 -*-
"""会议结构化记忆抽取：map-reduce 抽取 + 写入结构化表。"""
import json
import asyncio
from typing import List, Dict, Optional

from app.storage.db import get_connection
from app.llm.client import chat_json
from app.extract.prompts import build_map_messages, build_reduce_messages
from app.config import EXTRACT_WINDOW_CHARS, EXTRACT_CONCURRENCY

_VALID_ENTITY_TYPES = {"person", "project", "customer", "product"}


def _load_windows(note_id: str) -> List[str]:
    """按 chunk 顺序累计文本，分成 ~EXTRACT_WINDOW_CHARS 大小的窗口。"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT speaker, text FROM chunks WHERE note_id = ? ORDER BY chunk_index",
        (note_id,),
    ).fetchall()
    conn.close()

    windows: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for r in rows:
        piece = f"[发言人{r['speaker']}] {r['text']}"
        buf.append(piece)
        buf_len += len(r["text"])
        if buf_len >= EXTRACT_WINDOW_CHARS:
            windows.append("\n".join(buf))
            buf, buf_len = [], 0
    if buf:
        windows.append("\n".join(buf))
    return windows


async def _map_window(text: str, sem: asyncio.Semaphore) -> Optional[Dict]:
    async with sem:
        try:
            return await chat_json(build_map_messages(text))
        except Exception as e:
            print(f"  [warn] map 窗口抽取失败: {type(e).__name__}: {e}")
            return None


async def _extract_structured(note_id: str, title: str) -> Optional[Dict]:
    windows = _load_windows(note_id)
    if not windows:
        return None

    sem = asyncio.Semaphore(EXTRACT_CONCURRENCY)
    partials = await asyncio.gather(*[_map_window(w, sem) for w in windows])
    partials = [p for p in partials if p]
    if not partials:
        return None

    partials_json = json.dumps(partials, ensure_ascii=False, indent=2)
    final = await chat_json(build_reduce_messages(partials_json, title))
    return final


def _save(note_id: str, data: Dict) -> None:
    conn = get_connection()
    # 清理旧数据，保证重抽取幂等
    for table in ("meeting_summaries", "action_items", "decisions", "risks", "entities"):
        conn.execute(f"DELETE FROM {table} WHERE note_id = ?", (note_id,))

    conn.execute(
        "INSERT INTO meeting_summaries (note_id, summary, topics, key_points) VALUES (?, ?, ?, ?)",
        (
            note_id,
            data.get("summary", ""),
            json.dumps(data.get("topics", []), ensure_ascii=False),
            json.dumps(data.get("key_points", []), ensure_ascii=False),
        ),
    )

    for item in data.get("action_items", []):
        if isinstance(item, dict) and item.get("content"):
            conn.execute(
                "INSERT INTO action_items (note_id, content, owner, due) VALUES (?, ?, ?, ?)",
                (note_id, item["content"], item.get("owner", ""), item.get("due", "")),
            )

    for content in data.get("decisions", []):
        if content:
            conn.execute("INSERT INTO decisions (note_id, content) VALUES (?, ?)", (note_id, content))

    for content in data.get("risks", []):
        if content:
            conn.execute("INSERT INTO risks (note_id, content) VALUES (?, ?)", (note_id, content))

    for ent in data.get("entities", []):
        if isinstance(ent, dict) and ent.get("name"):
            etype = ent.get("type", "")
            if etype in _VALID_ENTITY_TYPES:
                conn.execute(
                    "INSERT INTO entities (note_id, entity_type, name) VALUES (?, ?, ?)",
                    (note_id, etype, ent["name"]),
                )

    conn.commit()
    conn.close()


async def extract_meeting(note_id: str, title: str) -> bool:
    """抽取单场会议并写入结构化表。成功返回 True。"""
    data = await _extract_structured(note_id, title)
    if not data:
        return False
    _save(note_id, data)
    return True
