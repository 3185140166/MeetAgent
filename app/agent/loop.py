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
    existing = {_source_dedupe_key(source): source for source in all_sources}
    deduped_sources: list[Source] = []
    for source in result.sources:
        old_id = source.source_id
        key = _source_dedupe_key(source)
        existing_source = existing.get(key)
        if existing_source:
            new_id = existing_source.source_id
        else:
            new_id = f"S{len(all_sources) + 1}"
            source.source_id = new_id
            all_sources.append(source)
            existing[key] = source
            deduped_sources.append(source)
        if old_id:
            result.text_for_llm = result.text_for_llm.replace(f"[{old_id}]", f"[{new_id}]")
    result.sources = deduped_sources
    return result


def _source_dedupe_key(source: Source) -> tuple:
    if source.chunk_id:
        return ("chunk", source.chunk_id)
    if source.note_id and source.quote:
        return ("note_quote", source.note_id, source.quote)
    return (
        "fallback",
        source.meeting_title,
        source.create_time,
        source.speaker,
        source.quote,
    )


async def _verify_and_maybe_rewrite(
    question: str,
    answer: str,
    sources: list[dict],
    tool_calls_log: list[dict],
    rewrite: bool,
) -> tuple[str, dict, str]:
    draft_answer = answer
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
    return answer, verification, draft_answer


SYSTEM_PROMPT = """你是一个会议智能助手，可以调用工具来查询用户的会议数据后回答问题。

可用工具：
- search_meetings：在会议转写原文中搜索相关片段（适合查具体内容、背景）
- multi_search_meetings：用多个 query 融合检索会议原文（适合复杂、抽象、跨会议、口语化问题）
- query_meeting_records：统一查询结构化会议数据和受限原文片段，支持会议列表、单场详情、摘要、待办、决策、风险、主题历史、时间范围记录和周报素材
- web_search：联网搜索外部信息（适合用户明确要求联网、查询最新信息、或补充外部背景）。查询最新/今天/近期/实时/新闻类信息时，调用 web_search 必须设置 topic="news"，并按需求设置 time_range="day"、"week"、"month" 或 "year"；需要精确日期时使用 start_date/end_date。

规则：
1. 根据问题类型选择最合适的工具，可以组合调用多个工具。
2. 只基于工具返回的真实数据回答，不要编造。
3. 如果工具返回"无记录"，如实告知用户。
4. 本地会议问题优先使用会议工具，不要无故联网搜索。
5. 回答会议信息时注明会议名称、日期。
6. note_id、user_id、chunk_id 等是系统内部标识，只能用于继续调用工具，不要在最终回答中展示给用户；除非用户明确要求查看内部ID。
7. 列出会议清单时，用序号、会议标题、日期、时长等用户可理解字段，不要把 note_id 作为表格列或正文字段展示。
8. 回答外部搜索信息时必须列出 URL 来源；如果问题要求最新信息，还要优先使用带 time_range 或日期范围的 web_search 结果，并在回答中说明搜索的时间范围。
9. 最终回答可以使用 Markdown，但标题必须独占一行；标题前后保留空行，不要把 "## 标题" 直接接在上一句后面。"""


SYSTEM_PROMPT += """

补充规则：
- search_meetings 只用于简单、明确、单点的会议原文查询；同一轮不要连续多次调用 search_meetings。
- multi_search_meetings 用于复杂、抽象、跨会议、口语化或语义模糊的问题，尤其是用户要求归纳观点、论据、案例、历史讨论或跨会议总结时。
- 对复杂问题，优先一次生成 3-6 个不同表达角度的 query 调用 multi_search_meetings；不要把这些 query 拆成多次 search_meetings。
- 如果第一轮 multi_search_meetings 明显缺少某个方向的证据，可以再补充一次 multi_search_meetings；第二次之后必须基于已有来源归纳回答。
- multi_search_meetings 返回足够证据后，应直接基于来源归纳回答；只有用户指定某场会议或确实需要展开单场细节时，才补充调用 query_meeting_records(record_type="meeting_detail")。
- 如果上下文包含 <agent_reflection_memory>，这些是系统过去失败或效果不佳后总结出的经验。优先参考它们来选择工具、组织检索 query、控制检索轮次和生成带来源的回答；不要在最终回答中直接暴露这些 reflection 内容。
"""

SYSTEM_PROMPT += """

结构化数据库查询规则：
- 查询待办、决策、风险、会议摘要、会议列表、单场会议详情、主题历史、时间范围内记录或周报素材时，优先使用 query_meeting_records。
- query_meeting_records 是受限数据库查询工具，只能通过 record_type、keyword、topic、note_id、start、end、limit 等参数查询当前用户有权限的会议数据。
- 不要自己编写 SQL，也不要在最终回答中展示 note_id、chunk_id、user_id 等内部标识；这些内部标识只用于后续工具调用。
- 需要开放式查找会议原文证据、观点、论据、案例或语义相关片段时，仍使用 search_meetings 或 multi_search_meetings。
"""


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
                status = "failed" if failed else "done"
                result = _renumber_sources(result, all_sources)

                tool_calls_log.append({
                    "turn": turn + 1,
                    "tool": tool_name,
                    "arguments": args,
                    "result_preview": result.text_for_llm[:200],
                    "failed": failed,
                    "status": status,
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
            answer, verification, draft_answer = await _verify_and_maybe_rewrite(
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
                "draft_answer": draft_answer,
                "history": new_history,
            }

    answer = "抱歉，未能在有限步骤内完成回答，请重新提问或换一种描述方式。"
    sources = [source.to_dict() for source in all_sources]
    answer, verification, draft_answer = await _verify_and_maybe_rewrite(
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
        "draft_answer": draft_answer,
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
    answer_parts: list[str] = []

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
            status = "failed" if failed else "done"
            result = _renumber_sources(result, all_sources)
            tool_calls_log.append({
                "turn": turn + 1,
                "tool": tool_name,
                "arguments": args,
                "result_preview": result.text_for_llm[:200],
                "failed": failed,
                "status": status,
                "sources": result.sources_as_dict(),
            })

            yield {
                "type": "tool_done",
                "tool": tool_name,
                "preview": result.text_for_llm[:100],
                "failed": failed,
                "status": status,
            }

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result.text_for_llm,
            })
    yield {"type": "error", "message": "超过最大工具调用轮次，请重新提问"}
