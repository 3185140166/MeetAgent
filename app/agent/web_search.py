# -*- coding: utf-8 -*-
"""Tavily web search wrapper for Agent tools."""

from typing import Any
import httpx

from app.config import TAVILY_API_KEY, TAVILY_API_URL, WEB_SEARCH_MAX_RESULTS


def search_web(query: str, max_results: int | None = None) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    if not TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY 未配置，无法联网搜索。")

    limit = max_results or WEB_SEARCH_MAX_RESULTS
    limit = min(max(int(limit), 1), 10)
    payload = {
        "query": query,
        "max_results": limit,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {
        "Authorization": f"Bearer {TAVILY_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(TAVILY_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
            "score": item.get("score"),
        })
    return results


def format_web_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "联网搜索没有找到结果。"

    lines = [f"联网搜索结果（共 {len(results)} 条）："]
    for i, item in enumerate(results, 1):
        title = item.get("title") or "无标题"
        url = item.get("url") or ""
        content = item.get("content") or ""
        lines.append(f"\n[{i}] {title}\nURL: {url}\n摘要: {content[:700]}")
    lines.append("\n回答涉及外部信息时，请在最终回答中列出 URL 来源。")
    return "\n".join(lines)
