# MeetAgent 可信会议 Agent 阶段 1 实施计划

## 目标

建立最小可信闭环：Agent 回答仍保持现有体验，但工具结果开始携带结构化来源，最终回答可以在前端展示“引用来源”。

阶段 1 不做 verifier、不做 reranker、不强制每句话都带 `[S1]`。先保证证据链路打通。

## 范围

本阶段实现：

1. 新增统一数据结构 `Source` / `ToolResult`。
2. 新增兼容式 `execute_tool_structured()`。
3. 保留旧 `execute_tool()`，避免影响后台任务和已有调用。
4. 优先结构化以下工具：
   - `search_meetings`
   - `get_action_items`
   - `get_decisions`
   - `get_risks`
   - `list_meetings`
5. Agent loop 汇总工具 sources。
6. `/agent/qa` 和 `/agent/qa/stream` 返回 sources。
7. 前端在回答下方展示引用来源。
8. 历史会话从 `tool_calls_log` 中恢复 sources 展示。

## 不做内容

- 不引入 verifier / 重写 Agent。
- 不引入 reranker。
- 不修改数据库 schema。
- 不强制 LLM 每个句子输出 `[S1]`。
- 不把 `note_id`、`chunk_id` 直接展示给普通用户。

## 数据结构

`Source` 用于表示可展示的证据来源：

```text
source_id      前端和回答中展示的引用编号，如 S1
note_id        内部会议 ID，仅后端使用
chunk_id       内部片段 ID，仅后端使用
meeting_title  会议标题
create_time    会议时间
speaker        发言人
quote          原文或结构化记录内容
score          可选分数
```

`ToolResult` 用于统一工具返回：

```text
ok            工具是否成功
tool          工具名
text_for_llm  给模型看的文本
data          给系统使用的结构化数据
sources       证据来源列表
error         错误信息
```

## 实施步骤

1. 新增 `app/agent/types.py`。
2. 改造 `app/agent/tools.py`：
   - 新增结构化工具实现。
   - `execute_tool_structured()` 返回 `ToolResult`。
   - `execute_tool()` 继续返回 `text_for_llm`。
3. 改造 `app/agent/loop.py`：
   - 使用结构化工具执行。
   - 汇总并重新编号 sources。
   - `run_agent()` 和 `run_agent_stream()` 返回 sources。
4. 改造 `app/main.py`：
   - Agent 响应模型增加 `sources`。
   - SSE done 事件携带 sources。
5. 改造 `app/agent/session.py`：
   - 从历史 `tool_calls_log` 中恢复 assistant 消息的 sources。
6. 改造前端：
   - 当前流式回答完成后记录 sources。
   - 历史消息加载 sources。
   - `ChatWindow` 在回答下方展示来源。

## 验收标准

1. 用户问会议相关问题时，回答下方出现“引用来源”。
2. 引用来源显示会议标题、日期、发言人和摘录。
3. 前端不显示 `note_id`、`chunk_id`、`user_id`。
4. 原有工具调用、流式回答、多会话后台运行不被破坏。
5. `python -m compileall app` 和 `npm run build` 通过。
