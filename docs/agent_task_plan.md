# Agent Task 系统规划

> 本文档规划 MeetAgent 后续引入“复杂任务 / 长任务 / 可恢复任务”能力的设计。目标不是替换当前同步 Agent，而是在现有即时问答之外增加一条可观察、可恢复、可后台执行的任务通道。

---

## 1. 背景

当前系统的 Agent 是 ReAct / function calling loop：

```text
用户问题
  -> LLM 判断是否调用工具
  -> 执行工具
  -> 工具结果回填
  -> LLM 继续判断
  -> 最终回答
```

这种模式适合：

- 简单问答。
- 单工具查询。
- 少量工具组合。
- 一次 HTTP 请求内可以完成的任务。

但它不适合：

- 跨大量会议的长时间分析。
- 多步骤任务规划。
- 后台执行。
- 失败后恢复。
- 用户查看任务进度。
- 服务重启后继续任务。

因此后续需要增加 Agent Task 系统。

---

## 2. 目标

Agent Task 系统要解决：

- 区分简单问题和复杂任务。
- 简单问题继续走现有同步 Agent。
- 复杂任务创建持久化任务。
- 每个复杂任务生成 plan 和 steps。
- 每个 step 的执行状态可记录、可展示、可恢复。
- worker 定期 heartbeat。
- 服务重启后能识别 pending / running / interrupted 任务。
- 用户可以在前端查看任务进度和最终结果。

---

## 3. 总体架构

```text
用户问题
  -> classify_complexity
       |
       |-- simple
       |     -> 现有 /agent/qa 或 /agent/qa/stream
       |
       |-- complex
             -> 创建 agent_tasks
             -> 生成 plan
             -> 写 agent_task_steps
             -> 返回 task_id
             -> worker 后台执行 steps
             -> 保存中间状态
             -> 汇总 final_answer
             -> 用户查看进度 / 最终结果
```

现有同步 Agent 保留，用于即时聊天。Agent Task 只负责复杂任务。

---

## 4. 适用场景

适合进入 Agent Task 的问题：

- “帮我分析过去三个月所有会议，整理项目风险。”
- “帮我生成一份完整月报。”
- “梳理某客户从首次出现到现在的所有进展。”
- “从所有会议里沉淀长期主题记忆。”
- “批量重建某个用户的结构化记忆。”
- “对某个项目做跨会议复盘，包括背景、决策、风险和待办。”

继续走同步 Agent 的问题：

- “我有哪些待办？”
- “最近有哪些风险？”
- “某场会议讲了什么？”
- “上周做了哪些决策？”
- “搜索一下某个关键词。”

---

## 5. 复杂度判断

第一阶段可以用规则判断，后续再引入 LLM classifier。

### 5.1 规则判断

命中以下特征时倾向复杂任务：

- 时间跨度大：三个月、半年、全年、所有会议。
- 明确要求“完整分析 / 复盘 / 报告 / 月报 / 总结所有”。
- 需要遍历大量会议。
- 需要多类信息汇总：摘要 + 决策 + 风险 + 待办 + 时间线。
- 用户明确要求“后台处理 / 生成报告 / 稍后查看”。

### 5.2 LLM 判断

后续可以加一个轻量 classifier：

```json
{
  "mode": "simple | complex",
  "reason": "判断原因",
  "task_type": "topic_analysis | weekly_report | memory_build | meeting_batch_extract | other"
}
```

---

## 6. 数据库设计

### 6.1 agent_tasks

主任务表。

```sql
CREATE TABLE IF NOT EXISTS agent_tasks (
  task_id TEXT PRIMARY KEY,
  session_id TEXT,
  user_id TEXT,
  question TEXT NOT NULL,
  task_type TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  plan TEXT,
  final_answer TEXT,
  error TEXT,
  current_step_index INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  started_at TEXT,
  finished_at TEXT,
  heartbeat_at TEXT
);
```

建议状态：

```text
pending
running
waiting
completed
failed
interrupted
canceled
```

字段说明：

- `task_id`：任务 ID。
- `session_id`：关联聊天 session。
- `user_id`：所属用户。
- `question`：用户原始问题。
- `task_type`：任务类型。
- `status`：任务整体状态。
- `plan`：LLM 生成的任务计划，JSON 或 Markdown。
- `final_answer`：最终汇总结果。
- `error`：失败原因。
- `current_step_index`：当前步骤位置，用于展示；恢复时以 steps 表为准。
- `heartbeat_at`：worker 心跳。

### 6.2 agent_task_steps

子步骤表。

```sql
CREATE TABLE IF NOT EXISTS agent_task_steps (
  step_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  step_index INTEGER NOT NULL,
  title TEXT,
  description TEXT,
  tool_name TEXT,
  tool_args TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  result TEXT,
  error TEXT,
  started_at TEXT,
  finished_at TEXT,
  FOREIGN KEY(task_id) REFERENCES agent_tasks(task_id)
);
```

建议状态：

```text
pending
running
completed
failed
skipped
```

字段说明：

- `step_index`：步骤顺序。
- `tool_name`：要调用的工具。
- `tool_args`：工具参数 JSON。
- `result`：工具返回或步骤产物。
- `error`：步骤失败原因。

### 6.3 agent_task_events

可选事件表。第一阶段可以不做，等需要更细粒度进度和审计时再加。

```sql
CREATE TABLE IF NOT EXISTS agent_task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  step_id TEXT,
  event_type TEXT NOT NULL,
  payload TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

可记录：

- task_created
- plan_generated
- step_started
- tool_called
- step_completed
- step_failed
- task_completed
- task_interrupted

---

## 7. Worker 设计

### 7.1 第一阶段：进程内后台 worker

本地原型阶段可以使用：

- FastAPI startup 时启动后台 loop。
- 定期扫描 `agent_tasks`。
- 找到 `pending` 或可恢复任务后执行。

适合本地演示，但进程退出时可能中断任务。

### 7.2 生产阶段：任务队列

生产建议迁移到：

- Redis Queue / RQ
- Celery
- Dramatiq
- Arq

并保留数据库任务表作为任务状态权威来源。

---

## 8. Heartbeat 与恢复

worker 执行任务时定期更新：

```text
agent_tasks.heartbeat_at
```

恢复策略：

1. 服务启动时扫描：

```text
pending
running
interrupted
```

2. 如果 `running` 任务的 `heartbeat_at` 超过阈值，比如 2 分钟：

```text
running -> interrupted
```

3. 恢复时不要盲目继续原 running step。

建议：

- 找到最后一个 `completed` step。
- 将未完成的 `running` step 标记为 `pending` 或 `failed`。
- 从下一个 pending step 重新执行。

---

## 9. 幂等要求

任务步骤必须尽量幂等。

高风险操作包括：

- 写入 Long-term Memory。
- 删除数据。
- 批量重建结构化记忆。
- 重建索引。

建议每个写操作都带：

- `task_id`
- `step_id`
- source marker

避免恢复重跑时重复写入。

---

## 10. API 设计

### 10.1 创建任务

```text
POST /agent/tasks
```

请求：

```json
{
  "question": "帮我分析过去三个月所有会议里的项目风险",
  "user_id": "1006734045",
  "session_id": "optional"
}
```

响应：

```json
{
  "task_id": "...",
  "status": "pending"
}
```

### 10.2 查看任务

```text
GET /agent/tasks/{task_id}
```

返回：

```json
{
  "task_id": "...",
  "status": "running",
  "question": "...",
  "plan": "...",
  "final_answer": null,
  "current_step_index": 2,
  "heartbeat_at": "..."
}
```

### 10.3 查看步骤

```text
GET /agent/tasks/{task_id}/steps
```

### 10.4 查看事件

```text
GET /agent/tasks/{task_id}/events
```

第一阶段可选。

### 10.5 取消任务

```text
POST /agent/tasks/{task_id}/cancel
```

将任务标记为 `canceled`，worker 在下一次 step 边界停止。

---

## 11. 前端设计

Admin 页面新增：

- 任务列表。
- 任务详情。
- step 进度。
- 当前状态。
- 最终结果。
- 失败原因。

聊天页中：

- 简单问题仍直接显示回答。
- 复杂问题显示“已创建任务”。
- 展示任务进度卡片。
- 支持点击进入任务详情。

---

## 12. 第一阶段 MVP

建议先做最小版本，不要一开始做通用 Agent 平台。

### 12.1 MVP 范围

只支持一种复杂任务：

```text
跨会议主题分析
```

例如：

```text
分析 1006734045 用户过去三个月关于某项目的风险、决策和待办。
```

### 12.2 MVP 步骤

1. 新增 `agent_tasks` 表。
2. 新增 `agent_task_steps` 表。
3. 新增 `app/agent/tasks.py`。
4. 新增 `app/agent/task_worker.py`。
5. 新增 `POST /agent/tasks`。
6. 新增 `GET /agent/tasks/{task_id}`。
7. 新增 `GET /agent/tasks/{task_id}/steps`。
8. Admin 页面增加任务列表和任务详情。
9. 先用进程内 worker。
10. 任务执行完成后写 `final_answer`。

### 12.3 MVP 不做

第一阶段暂不做：

- 分布式 worker。
- 多 worker 抢锁。
- 复杂重试策略。
- 任务事件流。
- 通用任意 plan 执行器。
- 任务结果向量化。

---

## 13. 第二阶段

第二阶段再扩展：

- 支持更多 `task_type`。
- 增加 `agent_task_events`。
- 增加 SSE 任务进度。
- 支持任务取消。
- 支持任务重试。
- 支持任务恢复。
- 将 worker 迁移到 Redis Queue / Celery。

---

## 14. 与现有系统的关系

现有系统继续保留：

- `/agent/qa`
- `/agent/qa/stream`
- Session Memory
- Long-term Memory
- 会议工具
- 联网搜索工具

Agent Task 是新增通道：

```text
即时问答：同步 Agent
复杂任务：Agent Task
```

不要让复杂任务系统替代当前同步 Agent。两者应该并存。

---

## 15. 推荐落地顺序

1. 添加任务表结构。
2. 做只读管理接口。
3. 实现任务创建接口。
4. 先 hard-code 一个 `topic_analysis` task type。
5. 实现 worker 执行 pending tasks。
6. Admin 可视化任务状态和 steps。
7. 增加 heartbeat。
8. 增加启动时 interrupted 检测。
9. 增加恢复策略。
10. 再考虑 LLM 自动规划复杂任务。
