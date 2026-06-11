# -*- coding: utf-8 -*-
import asyncio
import json
import httpx
from app.config import APIFUSION_API_URL, APIFUSION_API_KEY, APIFUSION_MODEL


async def chat(messages: list[dict], temperature: float = 0.2) -> str:
    if not APIFUSION_API_KEY:
        raise ValueError("APIFUSION_API_KEY 未设置，请检查 .env 文件")

    payload = {
        "model": APIFUSION_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {APIFUSION_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(APIFUSION_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def chat_sync(messages: list[dict], temperature: float = 0.2) -> str:
    return asyncio.run(chat(messages, temperature))


def _extract_json(text: str) -> str:
    """从模型输出中剥离 markdown 代码块，截取第一个 { 到最后一个 }。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```json ... ``` 包裹
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return text


async def chat_json(messages: list[dict], temperature: float = 0.0) -> dict:
    """调用大模型并将返回内容解析为 JSON 对象。"""
    raw = await chat(messages, temperature)
    return json.loads(_extract_json(raw))
