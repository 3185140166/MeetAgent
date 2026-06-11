# -*- coding: utf-8 -*-
from typing import List, Dict

SYSTEM_PROMPT = """你是一个会议智能问答助手。
你只能基于用户提供的会议片段回答问题。
如果会议片段中没有足够依据，请明确说"当前会议资料中没有找到明确依据"。
不要编造会议中没有出现的信息。
回答后必须列出引用来源，包括会议标题、会议时间、发言人和片段编号。"""


def build_context(chunks: List[Dict]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(
            f"[片段{i}] 会议：{c['title']} | 时间：{c['create_time']} | "
            f"发言人：{c['speaker']} | chunk#{c['chunk_index']}\n{c['text']}"
        )
    return "\n\n".join(parts)


def build_messages(question: str, chunks: List[Dict]) -> list[dict]:
    context = build_context(chunks)
    user_content = f"以下是相关会议片段：\n\n{context}\n\n请回答问题：{question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
