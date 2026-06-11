# -*- coding: utf-8 -*-
import asyncio
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

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(APIFUSION_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def chat_sync(messages: list[dict], temperature: float = 0.2) -> str:
    return asyncio.run(chat(messages, temperature))
