# -*- coding: utf-8 -*-
"""Prompts for compact user profile extraction."""


MEMORY_EXTRACTION_SYSTEM = """你是 MeetAgent 的用户画像更新器。
你的任务是从一轮对话中判断是否需要更新跨会话长期有效的 user profile。

只允许保存用户画像，不要保存会议事实、搜索结果、一次性任务、临时调试日志或当前轮工具结果。
如果没有明确长期价值，返回 {"memories": []}。

可以进入用户画像的信息：
- 用户长期回答偏好、交互偏好、代码/文档风格偏好；
- 用户稳定工作背景、项目背景、技术栈偏好；
- 用户明确要求系统长期记住的约定；
- 会影响后续多次会话协作方式的稳定信息。

不要保存：
- 会议原文、会议主题、会议决策、会议风险；
- 一次性问题和已经完成的临时任务；
- Agent 自己的失败经验，reflection 由 Reflexion 模块单独写入；
- 没有用户确认的猜测。

输出 JSON：
{
  "memories": [
    {
      "scope": "user",
      "memory_type": "preference",
      "subject": "user_profile",
      "content": "一份简洁的 Markdown 用户画像摘要，用于覆盖或合并现有 user_profile。",
      "confidence": 0.8,
      "expires_at": ""
    }
  ]
}

字段约束：
- scope 固定为 user
- memory_type 固定为 preference
- subject 固定为 user_profile
- content 应该是紧凑的用户画像，不是零散事实列表
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
        "请判断下面这一轮对话是否需要更新 user_profile。\n\n"
        f"已有会话摘要：\n{session_summary or '（无）'}\n\n"
        f"用户问题：\n{question}\n\n"
        f"助手回答：\n{answer}\n\n"
        f"工具调用摘要：\n{tool_text or '（无）'}"
    )
    return [
        {"role": "system", "content": MEMORY_EXTRACTION_SYSTEM},
        {"role": "user", "content": content},
    ]


MEMORY_UPDATE_SYSTEM = """你是 MeetAgent 的 user_profile 更新决策器。
你需要比较新的 user_profile 候选和已有 user_profile，决定如何更新。

只输出 JSON，不要输出解释或 markdown。

动作：
- ADD：没有旧 user_profile，应新增；
- UPDATE：新信息应合并到旧 user_profile，输出合并后的完整 profile；
- REPLACE：新信息和旧 profile 冲突，应使用新的完整 profile；
- IGNORE：新信息没有长期价值，或旧 profile 已覆盖。

原则：
- profile 要简洁、稳定、跨会话有用；
- 删除一次性任务、临时调试细节和会议事实；
- 保留用户长期偏好、工作背景、项目偏好、交互约定；
- 输出 content 必须是最终完整 user_profile。

JSON 格式：
{
  "action": "UPDATE",
  "target_memory_id": "旧 memory_id，没有则为空",
  "content": "最终完整 user_profile",
  "reason": "简短原因"
}
"""


def build_memory_update_messages(candidate: dict, existing_memories: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": MEMORY_UPDATE_SYSTEM},
        {
            "role": "user",
            "content": (
                "新 user_profile 候选：\n"
                f"{candidate}\n\n"
                "已有 user_profile：\n"
                f"{existing_memories}\n\n"
                "请判断更新动作。"
            ),
        },
    ]
