# -*- coding: utf-8 -*-
"""Prompts for long-term memory extraction."""


MEMORY_EXTRACTION_SYSTEM = """你是 Agent Memory 抽取器。你的任务是从一轮对话中判断是否存在值得跨 session 长期保存的信息。

只输出 JSON，不要输出解释或 markdown。

可以保存的信息：
- 用户明确表达的长期偏好
- 项目或环境中的稳定事实
- 用户明确要求“记住”的内容
- 后续多次 session 可能复用的长期任务背景或约定

不要保存的信息：
- 一次性命令输出
- 临时错误日志
- 当前轮工具结果细节
- 很快过期的短期任务进度
- 没有用户确认的猜测
- 敏感信息，除非用户明确要求记住

记忆内容必须写成事实陈述，不要写成命令。

JSON 格式：
{
  "memories": [
    {
      "scope": "user",
      "memory_type": "preference",
      "subject": "response_style",
      "content": "用户偏好回答先给结论，再给步骤。",
      "confidence": 0.8,
      "expires_at": ""
    }
  ]
}

字段约束：
- scope 只能是 user / project / meeting_topic
- memory_type 只能是 preference / fact / task / topic / decision / risk
- confidence 是 0 到 1 的数字
- 如果没有值得保存的信息，返回 {"memories": []}
"""


def build_memory_extraction_messages(
    *,
    question: str,
    answer: str,
    tool_calls_log: list,
    session_summary: str = "",
) -> list[dict]:
    tool_text = ""
    if tool_calls_log:
        lines = []
        for call in tool_calls_log:
            lines.append(
                f"- tool={call.get('tool')} args={call.get('arguments')} "
                f"failed={call.get('failed')} preview={call.get('result_preview')}"
            )
        tool_text = "\n".join(lines)

    content = (
        "请从下面这一轮对话中抽取长期记忆候选。\n\n"
        f"会话摘要：\n{session_summary or '（无）'}\n\n"
        f"用户问题：\n{question}\n\n"
        f"助手回答：\n{answer}\n\n"
        f"工具调用摘要：\n{tool_text or '（无）'}"
    )
    return [
        {"role": "system", "content": MEMORY_EXTRACTION_SYSTEM},
        {"role": "user", "content": content},
    ]


MEMORY_UPDATE_SYSTEM = """你是 Agent Memory 更新决策器。你需要比较一条新的 memory 候选和已有 memory，决定如何更新。

只输出 JSON，不要输出解释或 markdown。

动作：
- ADD：已有 memory 都不相似，新候选应新增。
- UPDATE：新旧信息互补，应合并到某条旧 memory。
- REPLACE：新候选与某条旧 memory 冲突，应废弃旧 memory，保存新 memory。
- IGNORE：新候选与旧 memory 重复，或不值得保存。

判断原则：
- 记忆内容必须是事实陈述，不是命令。
- 如果只是表达更完整，选 UPDATE。
- 如果直接矛盾，选 REPLACE。
- 如果几乎重复，选 IGNORE。
- 不要为了省事把无关内容合并。

JSON 格式：
{
  "action": "ADD",
  "target_memory_id": "",
  "content": "最终要保存的事实陈述；ADD/REPLACE/UPDATE 时填写",
  "reason": "简短原因"
}
"""


def build_memory_update_messages(candidate: dict, existing_memories: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": MEMORY_UPDATE_SYSTEM},
        {
            "role": "user",
            "content": (
                "新 memory 候选：\n"
                f"{candidate}\n\n"
                "已有 memory：\n"
                f"{existing_memories}\n\n"
                "请判断更新动作。"
            ),
        },
    ]
