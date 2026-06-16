# -*- coding: utf-8 -*-
"""Agent 主循环：LLM 决定调用工具 → 执行 → 返回结果 → 循环直到最终回答。"""

import json
from typing import Optional

from app.llm.client import chat_with_tools, chat_with_tools_stream
from app.agent.tools import TOOLS, execute_tool_structured
from app.agent.types import Source, ToolResult
from app.agent.verifier import rewrite_answer, verify_answer

_MAX_TOOL_FAILURES = 2


def _is_tool_failure(result: str) -> bool:
    markers = (
        "失败：",
        "未配置",
        "Traceback",
        "ConnectError",
        "ReadTimeout",
        "HTTPStatusError",
        "Timeout",
    )
    return any(marker in result for marker in markers)


def _blocked_tool_message(tool_name: str) -> str:
    return (
        f"工具 {tool_name} 已连续失败 {_MAX_TOOL_FAILURES} 次，本轮不再继续调用该工具。"
        "请改用其他工具；如果没有替代工具，请向用户说明失败原因和下一步建议。"
    )


def _execute_tool_with_guard(
    tool_name: str,
    args: dict,
    user_id: Optional[str],
    failure_counts: dict[str, int],
) -> tuple[ToolResult, bool]:
    if failure_counts.get(tool_name, 0) >= _MAX_TOOL_FAILURES:
        return ToolResult(
            ok=False,
            tool=tool_name,
            text_for_llm=_blocked_tool_message(tool_name),
            error=_blocked_tool_message(tool_name),
        ), True

    result = execute_tool_structured(tool_name, args, user_id)
    failed = _is_tool_failure(result.text_for_llm)
    if failed:
        failure_counts[tool_name] = failure_counts.get(tool_name, 0) + 1
    return result, failed


def _renumber_sources(result: ToolResult, all_sources: list[Source]) -> ToolResult:
    for source in result.sources:
        old_id = source.source_id
        new_id = f"S{len(all_sources) + 1}"
        source.source_id = new_id
        if old_id:
            result.text_for_llm = result.text_for_llm.replace(f"[{old_id}]", f"[{new_id}]")
        all_sources.append(source)
    return result


async def _verify_and_maybe_rewrite(
    question: str,
    answer: str,
    sources: list[dict],
    tool_calls_log: list[dict],
    rewrite: bool,
) -> tuple[str, dict]:
    verification = await verify_answer(
        question=question,
        answer=answer,
        sources=sources,
        tool_logs=tool_calls_log,
    )
    if rewrite and not verification.get("passed", True):
        answer = await rewrite_answer(
            question=question,
            draft_answer=answer,
            verification=verification,
            sources=sources,
        )
        verification = await verify_answer(
            question=question,
            answer=answer,
            sources=sources,
            tool_logs=tool_calls_log,
        )
    return answer, verification


SYSTEM_PROMPT = """你是一个会议智能助手，可以调用工具来查询用户的会议数据后回答问题。

可用工具：
- search_meetings：在会议转写原文中搜索相关片段（适合查具体内容、背景）
- get_action_items：查询结构化待办事项（适合"有哪些任务/待办"）
- get_decisions：查询决策记录（适合"做了哪些决定"）
- get_risks：查询风险项（适合"有哪些风险/问题"）
- get_meeting_summary：获取某场会议的摘要（需要 note_id）
- list_meetings：列出会议清单（适合查"最近开了哪些会"，或查 note_id）
- get_meeting_detail：获取某场会议详情、结构化记忆和部分原文（需要 note_id）
- search_by_time_range：按时间范围搜索会议内容（适合"上周/最近一个月"）
- get_topic_history：追踪某个主题、项目、客户或问题的历史讨论
- generate_weekly_report：基于会议摘要、待办、决策和风险生成周报素材
- web_search：联网搜索外部信息（适合用户明确要求联网、查询最新信息、或补充外部背景）。查询最新/今天/近期/实时/新闻类信息时，调用 web_search 必须设置 topic="news"，并按需求设置 time_range="day"、"week"、"month" 或 "year"；需要精确日期时使用 start_date/end_date。

规则：
1. 根据问题类型选择最合适的工具，可以组合调用多个工具。
2. 只基于工具返回的真实数据回答，不要编造。
3. 如果工具返回"无记录"，如实告知用户。
4. 本地会议问题优先使用会议工具，不要无故联网搜索。
5. 回答会议信息时注明会议名称、日期。
6. note_id、user_id、chunk_id 等是系统内部标识，只能用于继续调用工具，不要在最终回答中展示给用户；除非用户明确要求查看内部ID。
7. 列出会议清单时，用序号、会议标题、日期、时长等用户可理解字段，不要把 note_id 作为表格列或正文字段展示。
8. 回答外部搜索信息时必须列出 URL 来源；如果问题要求最新信息，还要优先使用带 time_range 或日期范围的 web_search 结果，并在回答中说明搜索的时间范围。"""


async def run_agent(
    question: str,
    user_id: Optional[str] = None,
    history: Optional[list] = None,
    memory_context: Optional[dict] = None,
    max_turns: int = 10,
) -> dict:
    """运行 Agent 循环，返回 {answer, tool_calls_log, history}。
    history 是上轮对话的 user/assistant 消息列表，会在本轮结束后追加并返回。
    """
    if history is None:
        history = []

    # system + 历史对话 + 本轮问题
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    if memory_context:
        messages.append(memory_context)
    messages.append({"role": "user", "content": question})

    tool_calls_log = []
    failure_counts: dict[str, int] = {}
    all_sources: list[Source] = []

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

                result, failed = _execute_tool_with_guard(tool_name, args, user_id, failure_counts)
                result = _renumber_sources(result, all_sources)

                tool_calls_log.append({
                    "turn": turn + 1,
                    "tool": tool_name,
                    "arguments": args,
                    "result_preview": result.text_for_llm[:200],
                    "failed": failed,
                    "sources": result.sources_as_dict(),
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result.text_for_llm,
                })
        else:
            answer = msg.get("content", "")
            sources = [source.to_dict() for source in all_sources]
            answer, verification = await _verify_and_maybe_rewrite(
                question=question,
                answer=answer,
                sources=sources,
                tool_calls_log=tool_calls_log,
                rewrite=True,
            )
            new_history = history + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
            return {
                "answer": answer,
                "tool_calls_log": tool_calls_log,
                "sources": sources,
                "verification": verification,
                "history": new_history,
            }

    answer = "抱歉，未能在有限步骤内完成回答，请重新提问或换一种描述方式。"
    sources = [source.to_dict() for source in all_sources]
    answer, verification = await _verify_and_maybe_rewrite(
        question=question,
        answer=answer,
        sources=sources,
        tool_calls_log=tool_calls_log,
        rewrite=True,
    )
    return {
        "answer": answer,
        "tool_calls_log": tool_calls_log,
        "sources": sources,
        "verification": verification,
        "history": history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
    }


async def run_agent_stream(
    question: str,
    user_id: Optional[str] = None,
    history: Optional[list] = None,
    memory_context: Optional[dict] = None,
    max_turns: int = 10,
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
    if memory_context:
        messages.append(memory_context)
    messages.append({"role": "user", "content": question})

    tool_calls_log = []
    failure_counts: dict[str, int] = {}
    all_sources: list[Source] = []

    for turn in range(max_turns):
        tool_message = None

        async for event in chat_with_tools_stream(messages, TOOLS):
            if event["type"] == "content":
                answer_parts.append(event["content"])
                yield {"type": "token", "content": event["content"]}
            elif event["type"] == "tool_calls":
                tool_message = event["message"]

        if not tool_message:
            answer = "".join(answer_parts)
            sources = [source.to_dict() for source in all_sources]
            verification = await verify_answer(
                question=question,
                answer=answer,
                sources=sources,
                tool_logs=tool_calls_log,
            )
            yield {
                "type": "done",
                "tool_calls_log": tool_calls_log,
                "sources": sources,
                "verification": verification,
            }
            return

        messages.append(tool_message)
        answer_parts = []
        for tc in tool_message.get("tool_calls", []):
            fn = tc["function"]
            tool_name = fn["name"]
            try:
                args = json.loads(fn["arguments"])
            except Exception:
                args = {}

            yield {"type": "tool_start", "tool": tool_name, "arguments": args}

            result, failed = _execute_tool_with_guard(tool_name, args, user_id, failure_counts)
            result = _renumber_sources(result, all_sources)
            tool_calls_log.append({
                "turn": turn + 1,
                "tool": tool_name,
                "arguments": args,
                "result_preview": result.text_for_llm[:200],
                "failed": failed,
                "sources": result.sources_as_dict(),
            })

            yield {"type": "tool_done", "tool": tool_name, "preview": result.text_for_llm[:100], "failed": failed}

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result.text_for_llm,
            })

    yield {"type": "error", "message": "超过最大工具调用轮次，请重新提问"}
