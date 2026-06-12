# -*- coding: utf-8 -*-
"""内存会话管理：按 session_id 存储多轮对话历史，30 分钟无操作自动过期。"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

_store: dict = {}  # session_id -> {history, user_id, last_active}
_TTL = timedelta(minutes=30)


def _evict():
    now = datetime.utcnow()
    expired = [sid for sid, s in _store.items() if now - s["last_active"] > _TTL]
    for sid in expired:
        del _store[sid]


def get_or_create(session_id: Optional[str], user_id: Optional[str]) -> tuple[str, list]:
    """返回 (session_id, history)。session_id 不存在或已过期则新建。"""
    _evict()
    now = datetime.utcnow()
    if session_id and session_id in _store:
        s = _store[session_id]
        s["last_active"] = now
        return session_id, s["history"]
    new_id = str(uuid.uuid4())
    _store[new_id] = {"history": [], "user_id": user_id, "last_active": now}
    return new_id, []


def update(session_id: str, history: list):
    if session_id in _store:
        _store[session_id]["history"] = history
        _store[session_id]["last_active"] = datetime.utcnow()


def clear(session_id: str):
    _store.pop(session_id, None)
