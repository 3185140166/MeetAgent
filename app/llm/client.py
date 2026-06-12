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


async def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.2,
) -> dict:
    """支持 function calling 的对话，返回 {finish_reason, message}。
    message 可能含 tool_calls（需继续执行工具）或 content（最终回答）。
    """
    if not APIFUSION_API_KEY:
        raise ValueError("APIFUSION_API_KEY 未设置，请检查 .env 文件")

    payload = {
        "model": APIFUSION_MODEL,
        "messages": messages,
        "tools": tools,
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

    choice = data["choices"][0]
    return {
        "finish_reason": choice.get("finish_reason", "stop"),
        "message": choice["message"],
    }
