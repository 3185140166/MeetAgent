# MeetAgent Agent Memory 实施计划

本文档描述 MeetAgent 引入 Agent Memory 的分阶段方案。这里的 Memory 不是现有会议结构化抽取的替代品，而是在现有会议问答、结构化会议记忆、Agent 工具调用之上，新增一层跨 session 的用户与项目长期记忆能力。

## 目标

当前系统已经支持：

- 会议原文导入与检索：`meetings`、`chunks`
- 会议结构化记忆：摘要、待办、决策、风险、实体
- Agent 工具调用：按问题选择会议检索、结构化查询、周报生成等工具
- 会话持久化：`chat_sessions`、`chat_messages`

新增 Memory 系统后，希望支持：

- 当前长会话能自动压缩，不必每轮塞入全部历史消息。
- 新 session 能召回用户偏好、项目事实、稳定约定和长期任务背景。
- 用户显式说“记住 / 忘记 / 不是这样”时，记忆能新增、删除或更新。
- 会议中反复出现的主题、项目、客户、长期风险可以沉淀为跨会议记忆。
- 记忆不会无脑膨胀，支持去重、合并、过期、降权和软删除。

## 总体架构

采用三层 Memory：

1. Working Memory
   当前一次 Agent loop 内的上下文，包括当前用户消息、工具调用、工具结果和本轮中间消息。现有 `app/agent/loop.py` 中的 `messages` 已经承担这部分职责。

2. Session Memory
   当前会话的压缩摘要，用来替代过长的历史消息。它解决上下文窗口和 token 成本问题，不作为永久记忆。

3. Long-term Memory
   跨 session 持久化记忆，保存用户偏好、项目事实、稳定约定、长期主题、历史任务背景和重要会议沉淀。

核心流转：

```text
Working Memory  --compact-->  Session Memory
Session / Turn   --extract-->  Long-term Memory
Long-term Memory --retrieve--> Working Memory
```

## 阶段一：Session Memory

### 目标

先解决长会话历史越来越长的问题。当前 `chat_messages` 会保存完整历史，如果一个 session 交互很多轮，后续每次都加载全量历史会增加 token 成本，也容易让模型分散注意力。

### 当前实现状态

已实现。Session Memory 绑定具体 `session_id`，本质是该会话的压缩摘要，生命周期与会话一致。删除会话时，会同步删除该会话的 `chat_messages`、`chat_sessions` 和 `session_summaries`；它不会沉淀为跨会话长期记忆，也不会影响后续 Long-term Memory 的设计。

### 数据表

新增：

```sql
CREATE TABLE IF NOT EXISTS session_summaries (
  session_id TEXT PRIMARY KEY,
  user_id TEXT,
  summary TEXT NOT NULL,
  message_count INTEGER DEFAULT 0,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
);
```

### 实现点

- 在 `app/agent/session.py` 增加：
  - `get_compacted_history(session_id, recent_limit=6)`
  - `maybe_update_summary(session_id, threshold_messages=12)`
  - `build_session_summary(messages)`
- 在 `/agent/qa` 和 `/agent/qa/stream` 保存一轮对话后触发 summary 更新。
- 下一轮同 session 问答时，加载：
  - session summary
  - 最近若干条原始消息
  - 当前用户问题

### 注入格式

不要把 session summary 塞进 system prompt，建议作为 meta message 放到当前用户问题之前：

```text
<session_memory>
以下是当前会话摘要，不是用户当前输入：
...
</session_memory>
```

### 验收标准

- 同一 session 超过阈值后生成 `session_summaries`。
- 后续请求不会加载全量历史，只加载摘要 + 最近消息。
- 追问仍能理解当前会话内的关键上下文。

## 阶段二：Long-term Memory 表与基础 CRUD

### 目标

建立长期记忆的持久化模型，先做到可写、可查、可看，不急于自动化。

### 当前实现状态

已实现基础版。当前阶段只提供 Long-term Memory 的表结构、CRUD、FTS 同步、手动新增和查看脚本；不会自动从会话中抽取长期记忆，也不会自动注入 Agent 上下文。自动抽取属于阶段三，检索注入属于阶段五。

### 数据表

新增：

```sql
CREATE TABLE IF NOT EXISTS memories (
  memory_id TEXT PRIMARY KEY,
  user_id TEXT,
  scope TEXT NOT NULL,          -- user / project / meeting_topic
  memory_type TEXT NOT NULL,    -- preference / fact / task / topic / decision / risk
  subject TEXT,
  content TEXT NOT NULL,
  status TEXT DEFAULT 'active', -- active / deprecated / deleted / expired
  trust_score REAL DEFAULT 0.7,
  source_type TEXT,             -- chat / meeting / extracted_meeting / manual
  source_id TEXT,               -- session_id / note_id / other id
  evidence TEXT,                -- JSON
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  expires_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  memory_id UNINDEXED,
  user_id UNINDEXED,
  subject,
  content
);
```

### 模块

新增 `app/memory/`：

- `store.py`
  - `add_memory`
  - `update_memory`
  - `search_memories`
  - `mark_deprecated`
  - `mark_deleted`
  - `expire_old_memories`
- `schemas.py`
  - 记忆类型、状态、检索结果的数据结构
- `__init__.py`

新增脚本：

- `scripts/show_memories.py`
- `scripts/add_memory.py`，可选，用于手动测试

### 写入原则

长期记忆必须写成事实陈述，而不是命令：

好：

```text
用户偏好回答先给结论，再给步骤。
项目后端使用 FastAPI，数据库使用 SQLite。
```

不好：

```text
以后你必须先给结论。
每次都用 SQLite。
```

### 验收标准

- 可以手动新增 memory。
- 可以按 `user_id` 和关键词查 memory。
- `memory_fts` 与 `memories` 保持同步。
- `deleted / deprecated / expired` 状态默认不参与召回。

## 阶段三：Stop Hook Extraction

### 目标

在一轮对话结束后，从用户问题、助手回答、工具调用中抽取值得长期保存的信息。不要在每个 tool call 后写记忆，避免噪声。

### 当前实现状态

已实现基础版。`/agent/qa` 和 `/agent/qa/stream` 在保存一轮回答后会执行 Stop Hook：先尝试更新 Session Memory，再尝试抽取 Long-term Memory。长期记忆抽取默认关闭，需要设置 `MEMORY_EXTRACTION_ENABLED=true`；也可以用 `scripts/extract_memories.py <session_id> --force` 对指定会话最后一轮强制抽取。当前阶段只做 ADD，不做冲突合并、替换和删除，更新策略属于阶段四。

### 触发点

非流式接口：

```text
app/main.py -> /agent/qa -> sess.append_turn() 后
```

流式接口：

```text
app/main.py -> /agent/qa/stream -> answer 保存后
```

### 模块

新增：

- `app/memory/extractor.py`
  - `extract_memory_candidates(session_id, question, answer, tool_calls_log)`
  - `should_extract_memory(...)`
- `app/memory/prompts.py`
  - extraction prompt
  - update decision prompt

### 抽取输出

LLM 输出 JSON：

```json
{
  "memories": [
    {
      "scope": "user",
      "memory_type": "preference",
      "subject": "response_style",
      "content": "用户偏好直接、实用的回答，避免在未确认前直接实现代码。",
      "confidence": 0.8,
      "expires_at": ""
    }
  ]
}
```

### 值得记的信息

- 用户明确表达的偏好
- 项目稳定事实
- 团队约定
- 长期任务背景
- 用户明确说“记住”的内容
- 后续多次 session 可能复用的信息

### 不值得记的信息

- 一次性命令输出
- 临时错误日志
- 当前轮工具结果细节
- 很快过期的任务进度
- 没有用户确认的猜测
- 敏感信息，除非业务明确需要且用户授权

### 验收标准

- 用户说“记住，我喜欢简洁回答”后，`memories` 中新增偏好。
- 用户普通提问不会产生大量无意义 memory。
- extraction 失败不影响主问答流程。

## 阶段四：Memory Update

### 目标

避免只新增不更新导致记忆库膨胀、重复和冲突。

### 当前实现状态

已实现基础版。新候选 memory 写入前会查相似 active memory；存在相似项时由 LLM 判断 `ADD / UPDATE / REPLACE / IGNORE`。`REPLACE` 会把旧 memory 标记为 `deprecated`，不会物理删除。

### 更新动作

- `ADD`：没有相似旧记忆，新增。
- `UPDATE`：新旧信息互补，合并成一条。
- `REPLACE`：新旧信息冲突，新记忆替代旧记忆，旧记忆标记 `deprecated`。
- `DELETE`：用户明确要求忘记，标记 `deleted`。
- `IGNORE`：候选信息不值得保存或重复。

### 实现策略

第一版可以用 FTS 查相似记忆：

```text
候选 memory
  -> search similar active memories by user_id + subject/content
  -> LLM 判断 ADD / UPDATE / REPLACE / IGNORE
  -> 写库
```

后续可引入向量相似度或 NLI 判断。

### 用户纠正

当用户说：

```text
不是，我不是喜欢详细回答，我喜欢简短。
```

应触发：

```text
旧 memory status = deprecated
新 memory status = active
```

当用户说：

```text
忘记我刚才说的这个偏好。
```

应触发：

```text
status = deleted
```

### 验收标准

- 同类偏好不会无限新增重复记录。
- 明确冲突时旧记忆被软废弃。
- 用户要求忘记时不再召回相关记忆。

## 阶段五：Memory Retrieval 与 Agent 注入

### 目标

在每轮 Agent 开始前，判断是否需要查长期记忆，召回相关 memory，并注入到当前上下文。

### 当前实现状态

已实现基础版，默认关闭。设置 `MEMORY_RETRIEVAL_ENABLED=true` 后，系统会用规则 Router 判断是否召回长期记忆，并把命中的 memory 作为 `<memory>` meta message 注入到当前用户问题之前。

### Router

先做规则版 Router。以下情况建议查 memory：

- 用户提到“之前、上次、继续、记得、忘记、偏好、我喜欢、我们说过”
- 用户询问项目背景、长期约定、历史任务
- 用户询问某主题、项目、客户、产品的历史脉络

以下情况默认不查：

- 问候
- 通用知识解释
- 明确一次性问题
- 与用户历史无关的简单代码片段

### 检索

第一版：

- FTS 关键词检索
- 按 `trust_score`、更新时间、状态过滤排序
- Top-K 截断，默认 3-5 条

后续：

- 加 embedding 检索
- 关键词 + 向量融合
- 结合会议实体做图检索

### 注入格式

使用 meta user message：

```text
<memory>
以下是系统召回的历史记忆，不是用户当前输入。若与当前用户指令冲突，以当前用户指令为准。
1. 用户偏好回答先给结论，再给步骤。
2. 项目后端使用 FastAPI，数据库使用 SQLite。
</memory>
```

### Agent 改动

- `app/agent/loop.py`
  - `run_agent(..., memory_context=None)`
  - 在当前用户问题前插入 memory message
- `app/main.py`
  - 调用 Agent 前执行 memory router + retrieval
- `app/agent/tools.py`
  - 可选新增 `search_memory` 工具，让 LLM 主动查记忆

推荐第一版先自动注入，不急着开放工具。

### 验收标准

- 新 session 中，用户偏好仍能影响回答风格。
- 当前用户指令能覆盖旧记忆。
- 无关问题不会召回大量 memory。

## 阶段六：会议结构化记忆沉淀为长期主题记忆

### 目标

把已有会议结构化记忆转为少量高价值长期记忆，而不是把所有会议内容重复存一遍。

### 当前实现状态

已实现基础版脚本：`scripts/build_meeting_memories.py`。它从 `meeting_summaries.topics` 中统计多场会议反复出现的主题，生成 `meeting_topic/topic` 类型的长期记忆，并保留来源会议 evidence。

### 来源

使用现有表：

- `meeting_summaries`
- `action_items`
- `decisions`
- `risks`
- `entities`

### 策略

只沉淀：

- 高频主题
- 多次出现的人、项目、客户、产品
- 多场会议反复出现的风险
- 已形成稳定结论的决策
- 用户明确要求记住的会议结论

不要沉淀：

- 每个实体
- 每条待办
- 每条会议摘要全文
- 单次出现且无长期价值的信息

### 脚本

新增：

```bash
python scripts/build_meeting_memories.py --user-id <user_id>
```

输出 memory 示例：

```text
成长架构主题在 2025-11-08 到 2025-12-22 的多场会议中反复出现，主要涉及亲子陪伴营、课程成交、活动复盘、家长教育和安全管理。
```

`source_type` 使用：

```text
extracted_meeting
```

`evidence` 保存来源会议：

```json
[
  {"note_id": "...", "title": "...", "create_time": "..."}
]
```

### 验收标准

- 可以从已抽取会议中生成少量长期主题记忆。
- 回答“这个主题之前怎么讨论的”时，能先召回长期主题记忆，再按需调用会议工具取证。
- 记忆数量不会随会议数量线性爆炸。

## 阶段七：Trust Score 与自净化

### 目标

让错误、过期、低价值记忆自然沉下去。

### 当前实现状态

已实现基础版。`scripts/clean_memories.py` 会把过期 memory 标记为 `expired`，把长期未更新且低于 trust 阈值的 active memory 标记为 `deprecated`，并重建 FTS；不会物理删除。

### 初始规则

- 新增记忆：`trust_score = 0.7`
- 用户明确确认：`+0.1`
- 被召回并用于回答：`+0.02`
- 用户纠正：`-0.2`
- 低于 `0.3`：默认不召回
- 用户要求忘记：`status = deleted`

### 清理脚本

新增：

```bash
python scripts/clean_memories.py
```

处理：

- 过期记忆标记为 `expired`
- 低 trust 且长期未命中的记忆标记为 `deprecated`
- 输出清理报告

### 验收标准

- 过期 memory 不再召回。
- 被用户纠正过的 memory 权重降低或被替换。
- 记忆库不会只增不减。

## 测试方案

### 1. Session Memory 测试

连续问答超过阈值后，确认：

- `session_summaries` 有记录。
- 后续对话仍能理解前文。
- `chat_messages` 全量历史没有全部注入 prompt。

### 2. 用户偏好测试

```text
用户：记住，我喜欢回答先给结论，再给步骤。
新 session：这个项目 Memory 应该怎么做？
```

预期：

- 召回偏好 memory。
- 回答风格先给结论。

### 3. 纠正测试

```text
用户：不是，我不是喜欢详细，我喜欢简短。
```

预期：

- 旧偏好被 `deprecated`。
- 新偏好生效。

### 4. 忘记测试

```text
用户：忘记我关于回答风格的偏好。
```

预期：

- 相关 memory 状态为 `deleted`。
- 后续不再召回。

### 5. 会议主题测试

先运行：

```bash
python scripts/extract_user.py --user-id 1006734045 --limit 25
python scripts/build_meeting_memories.py --user-id 1006734045
```

再问：

```text
成长架构之前主要讨论过哪些问题？按时间线总结。
```

预期：

- 先召回长期主题记忆。
- 必要时调用会议工具补充来源。
- 回答包含会议名称和日期。

## 实施优先级

推荐顺序：

1. Session Memory
2. Long-term Memory 表与 CRUD
3. Stop Hook Extraction
4. Memory Update
5. Retrieval 注入 Agent
6. 会议结构化记忆沉淀
7. Trust Score 与清理

第一版 MVP 建议只做 1、2、3、5：

- 能压缩长会话。
- 能从对话中抽取用户偏好和项目事实。
- 能在新 session 召回并注入。
- 能通过脚本查看和调试。

会议沉淀、复杂更新和自净化可以放到第二轮。
