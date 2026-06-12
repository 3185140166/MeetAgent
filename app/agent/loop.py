# -*- coding: utf-8 -*-
"""Agent 主循环：LLM 决定调用工具 → 执行 → 返回结果 → 循环直到最终回答。"""

import json
from typing import Optional

from app.llm.client import chat_with_tools, chat_stream
from app.agent.tools import TOOLS, execute_tool

SYSTEM_PROMPT = """你是一个会议智能助手，可以调用工具来查询用户的会议数据后回答问题。

可用工具：
- search_meetings：在会议转写原文中搜索相关片段（适合查具体内容、背景）
- get_action_items：查询结构化待办事项（适合"有哪些任务/待办"）
- get_decisions：查询决策记录（适合"做了哪些决定"）
- get_risks：查询风险项（适合"有哪些风险/问题"）
- get_meeting_summary：获取某场会议的摘要（需要 note_id）
- list_meetings：列出会议清单（适合查"最近开了哪些会"，或查 note_id）

规则：
1. 根据问题类型选择最合适的工具，可以组合调用多个工具。
2. 只基于工具返回的真实数据回答，不要编造。
3. 如果工具返回"无记录"，如实告知用户。
4. 回答时注明信息来源（会议名称、日期）。"""


async def run_agent(
    question: str,
    user_id: Optional[str] = None,
    history: Optional[list] = None,
    max_turns: int = 5,
) -> dict:
    """运行 Agent 循环，返回 {answer, tool_calls_log, history}。
    history 是上轮对话的 user/assistant 消息列表，会在本轮结束后追加并返回。
    """
    if history is None:
        history = []

    # system + 历史对话 + 本轮问题
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    tool_calls_log = []

    for turn in range(max_turns):
        response = await chat_with_tools(messages, TOOLS)
        finish_reason = response["finish_reason"]
        msg = response["message"]

        if finish_reason == "tool_calls":
            messages.append(msg)

            for tc in msg.get("tool_calls", []):
                fn = tc["function"]
                tool_name = fn["name"]
                try:
                    args = json.loads(fn["arguments"])
                except Exception:
                    args = {}

                result = execute_tool(tool_name, args, user_id)

                tool_calls_log.append({
                    "turn": turn + 1,
                    "tool": tool_name,
                    "arguments": args,
                    "result_preview": result[:200],
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
        else:
            answer = msg.get("content", "")
            new_history = history + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
            return {
                "answer": answer,
                "tool_calls_log": tool_calls_log,
                "history": new_history,
            }

    answer = "抱歉，未能在有限步骤内完成回答，请重新提问或换一种描述方式。"
    return {
        "answer": answer,
        "tool_calls_log": tool_calls_log,
        "history": history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
    }


async def run_agent_stream(
    question: str,
    user_id: Optional[str] = None,
    history: Optional[list] = None,
    max_turns: int = 5,
):
    """流式 Agent 循环。yield 事件 dict：
    - {"type": "tool_start", "tool": str, "arguments": dict}
    - {"type": "tool_done",  "tool": str, "preview": str}
    - {"type": "token",      "content": str}
    - {"type": "done",       "tool_calls_log": list}
    - {"type": "error",      "message": str}
    工具调用轮次非流式等待，最终回答轮次切换 stream=True 逐 token 输出。
    """
    if history is None:
        history = []

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    tool_calls_log = []

    for turn in range(max_turns):
        response = await chat_with_tools(messages, TOOLS)
        finish_reason = response["finish_reason"]
        msg = response["message"]

        if finish_reason == "tool_calls":
            messages.append(msg)
            for tc in msg.get("tool_calls", []):
                fn = tc["function"]
                tool_name = fn["name"]
                try:
                    args = json.loads(fn["arguments"])
                except Exception:
                    args = {}

                yield {"type": "tool_start", "tool": tool_name, "arguments": args}

                result = execute_tool(tool_name, args, user_id)
                tool_calls_log.append({
                    "turn": turn + 1,
                    "tool": tool_name,
                    "arguments": args,
                    "result_preview": result[:200],
                })

                yield {"type": "tool_done", "tool": tool_name, "preview": result[:100]}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
        else:
            # 最终回答：用流式接口逐 token 输出
            async for token in chat_stream(messages):
                yield {"type": "token", "content": token}
            yield {"type": "done", "tool_calls_log": tool_calls_log}
            return

    yield {"type": "error", "message": "超过最大工具调用轮次，请重新提问"}
