# -*- coding: utf-8 -*-
"""Build sparse-search queries for SQLite FTS5."""

from __future__ import annotations

import json
from functools import lru_cache

import httpx

from app.config import (
    APIFUSION_API_KEY,
    APIFUSION_API_URL,
    APIFUSION_MODEL,
    LLM_SPARSE_QUERY_MAX_TERMS,
)


_SYSTEM_PROMPT = """你是会议检索系统的稀疏检索关键词生成器。
任务：把用户的自然语言问题改写成适合 BM25/FTS 检索的中文关键词或短语。
要求：
- 只输出 JSON，不要 markdown。
- 输出格式：{"terms":["关键词1","关键词2"]}
- terms 中放最重要的实体、主题、动作、时间、人名、术语。
- 删除“帮我查/有没有/相关内容/主要讲了什么”等泛化问法。
- 保留可能在会议原文中出现的原词，不要解释，不要生成完整答案。
- 最多输出指定数量的 terms。
"""


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


def _clean_terms(values, max_terms: int) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        term = str(value or "").strip()
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


@lru_cache(maxsize=512)
def extract_sparse_terms(query: str, max_terms: int = LLM_SPARSE_QUERY_MAX_TERMS) -> list[str]:
    """Use the configured LLM to extract sparse-search terms from a query."""
    query = (query or "").strip()
    if not query or not APIFUSION_API_KEY:
        return []

    payload = {
        "model": APIFUSION_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"最多输出 {max_terms} 个 terms。\n"
                    f"用户问题：{query}"
                ),
            },
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {APIFUSION_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(APIFUSION_API_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _extract_json(content)
        return _clean_terms(parsed.get("terms"), max_terms)
    except Exception:
        return []


def build_fts_or_query(terms: list[str]) -> str:
    """Build a conservative OR query for SQLite FTS5 MATCH."""
    parts = []
    for term in terms:
        term = str(term or "").strip()
        if not term:
            continue
        escaped = term.replace('"', '""')
        parts.append(f'"{escaped}"')
    return " OR ".join(parts)


def build_llm_sparse_match_query(query: str) -> tuple[str, list[str]]:
    terms = extract_sparse_terms(query)
    return build_fts_or_query(terms), terms
