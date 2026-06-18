# MeetAgent

MeetAgent 是一个面向本地会议数据的可信会议问答系统。它将会议转写、摘要、待办、决策、风险等数据导入 SQLite，通过 BM25/可选向量混合检索、Agent 工具调用和大模型回答，支持跨会议检索、主题追踪、来源引用、执行步骤展示、长期记忆和离线训练闭环。

## 核心能力

- 会议数据导入：将会议 JSON 导入本地 SQLite，会议原文切分为 chunks，并建立 FTS 检索索引。
- 会议原文问答：基于 `search_meetings` 和 `multi_search_meetings` 检索会议片段，回答时附带来源。
- 多角度检索：复杂、抽象、跨会议、口语化问题优先使用 `multi_search_meetings`，在工具内部完成多 query 召回、去重和融合排序。
- 结构化会议查询：支持待办、决策、风险、会议摘要、会议详情、时间范围检索和主题历史追踪。
- Agent ReAct 循环：大模型自动选择工具、读取工具结果、继续检索或生成最终回答。
- SSE 流式输出：前端实时展示 token、工具执行步骤和最终答案。
- 引用来源管理：来源按 chunk/note/quote 去重，前端默认展示少量来源，可展开查看全部。
- Session Memory：长会话自动压缩为摘要，保留最近消息，降低上下文膨胀。
- Long-term Memory：长期记忆收敛为 `user_profile` 和 `reflection` 两类，避免把会议事实复制成第二知识库。
- Reflexion Memory：根据工具失败、证据不足、verifier 失败、用户纠错或用户认可沉淀可复用经验。
- 训练闭环工具：`training_loop/` 独立于运行时代码，支持样本审核、JSONL 导出和评测集模板。

## 技术栈

- 后端：FastAPI、SQLite、FTS5、SSE
- 前端：React/Vite
- Agent：ReAct + function calling/tool calling
- 检索：BM25/FTS，可选 ChromaDB + embedding 混合检索
- 大模型接口：OpenAI Chat Completions 兼容接口，通过 `.env` 配置
- 训练闭环：基于 `agent_eval_samples` 的离线审核和导出工具

## 数据库中的主要数据

会议知识库数据：

- `meetings`
- `chunks`
- `fts_chunks`
- `meeting_summaries`
- `action_items`
- `decisions`
- `risks`
- `entities`

会话数据：

- `chat_sessions`
- `chat_messages`
- `session_summaries`

长期记忆：

- `memories`
- `memory_fts`

当前长期记忆只主动使用两类：

- `preference`：用户画像，`subject=user_profile`，每个用户维护一条 compact profile。
- `reflection`：Agent 反思经验，多条，通过 `subject` 区分工具策略、检索策略、回答结构、用户反馈和成功模式。

训练/评估数据：

- `agent_eval_samples`

## 记忆系统

MeetAgent 当前不再把 `fact/task/topic/decision/risk` 写入长期记忆。会议事实、主题、决策和风险继续保存在会议库和结构化表中，长期记忆只保存会影响后续协作和 Agent 行为的内容。

### User Profile

`user_profile` 用于描述用户长期稳定偏好，例如：

- 回答风格偏好
- 技术解释深度
- 工程实践习惯
- 当前长期关注方向
- 交互约定

存储形式：

```text
scope = user
memory_type = preference
subject = user_profile
```

### Agent Reflection

`reflection` 用于保存 Agent 的可复用经验，来源包括：

- 系统自评失败：verifier 失败、工具失败、来源不足、检索轮次过多。
- 用户负反馈：用户指出不对、重复、来源错误、理解偏差等。
- 用户正反馈：用户认可某个方案、结构或处理方式。

常见 `subject`：

```text
tool_use:strategy
retrieval:strategy
answer:structure
answer:citation
user_feedback:correction
user_feedback:missing_expectation
success_pattern:meeting_qa
success_pattern:memory_design
success_pattern:debugging
```

问答前会召回 `user_profile` 和相关 `reflection`，注入到 Agent 上下文中；问答结束后，后台 stop hook 会更新 session summary、user profile、系统反思和用户反馈反思。

## 训练闭环

训练闭环工具位于：

```text
training_loop/
```

该目录和运行时 `app/` 代码分离，只读取现有 SQLite 数据库，不接入 FastAPI/Agent 运行链路。

文档：

- [English](training_loop/README.md)
- [中文](training_loop/README.zh-CN.md)

基本流程：

```text
线上问答 -> agent_eval_samples -> 人工审核 -> JSONL 导出 -> 微调训练 -> 固定评测 -> 上线决策
```

查看样本池：

```powershell
python training_loop/review_samples.py summary
python training_loop/review_samples.py list --limit 20
python training_loop/review_samples.py show <sample_id>
```

审核样本：

```powershell
python training_loop/review_samples.py mark <sample_id> --status accepted
python training_loop/review_samples.py mark <sample_id> --status rejected
python training_loop/review_samples.py mark <sample_id> --status fixed
```

导出训练数据：

```powershell
python training_loop/export_datasets.py --type tool_call --review-status accepted --passed-only --output data/training/tool_call.jsonl
python training_loop/export_datasets.py --type answer_generation --review-status accepted --passed-only --output data/training/answer_generation.jsonl
python training_loop/export_datasets.py --type preference --review-status accepted --output data/training/preference.jsonl
```

建议优先训练：

1. 工具调用策略：用户问题 -> 工具名和参数。
2. 基于来源的回答生成：问题 + 工具结果 + sources -> 可信答案。
3. verifier/judge：问题 + 答案 + sources -> 质量判断。
4. reflection/feedback reflection：失败轨迹或用户反馈 -> 可复用经验。

## 快速开始

### 1. 创建环境

推荐使用 Conda：

```bash
conda create -n meetagent python=3.13
conda activate meetagent
pip install -r requirements.txt
```

也可以使用 venv：

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example`：

```bash
cp .env.example .env
```

核心配置：

```env
APIFUSION_API_URL=https://apifusion.aispeech.com.cn/v1/chat/completions
APIFUSION_API_KEY=your_api_key_here
APIFUSION_MODEL=gpt-5.5

DB_PATH=data/meetagent.db
TOP_K=8

ENABLE_HYBRID_SEARCH=false

MEMORY_EXTRACTION_ENABLED=true
MEMORY_RETRIEVAL_ENABLED=true
REFLEXION_ENABLED=true

TAVILY_API_KEY=your_tavily_key_here
```

如果本地 embedding 模型和向量索引尚未准备好，建议保持：

```env
ENABLE_HYBRID_SEARCH=false
```

准备好 `models/` 和 `data/chroma/` 后再开启混合检索。

### 3. 导入会议数据

将会议 JSON 文件放入 `test_meetingdata/`，然后执行：

```bash
python -m app.ingest.import_meetings test_meetingdata
```

重复执行是安全的，已导入会议会自动跳过。

### 4. 离线结构化抽取

导入会议后，可以抽取会议摘要、待办、决策、风险和实体：

```bash
python scripts/stats.py
python scripts/extract_user.py --user-id <user_id> --limit 25
python scripts/extract_user.py --user-id <user_id> --dry-run
```

### 5. 可选：构建向量索引

```bash
python scripts/build_index.py --user-id <user_id>
python scripts/build_index.py
python scripts/build_index.py --user-id <user_id> --batch-size 64
```

向量索引保存到：

```text
data/chroma/
```

## 启动服务

启动后端：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问 API 文档：

```text
http://localhost:8000/docs
```

启动前端：

```bash
cd frontend
npm install
npm run dev
```

## 常用接口

普通 Agent 问答：

```http
POST /agent/qa
```

流式 Agent 问答：

```http
POST /agent/qa/stream
```

会话列表：

```http
GET /sessions
```

长期记忆查看：

```http
GET /memories
```

管理页数据：

```http
GET /admin/overview
```

## Agent 工具

| 工具 | 作用 |
| --- | --- |
| `search_meetings` | 单 query 检索会议原文，适合具体、明确、单点问题 |
| `multi_search_meetings` | 多 query 融合检索，适合复杂、抽象、跨会议、口语化问题 |
| `get_action_items` | 查询结构化待办 |
| `get_decisions` | 查询结构化决策 |
| `get_risks` | 查询结构化风险 |
| `get_meeting_summary` | 获取单场会议摘要 |
| `list_meetings` | 列出会议清单 |
| `get_meeting_detail` | 获取单场会议详情、结构化信息和部分原文 |
| `search_by_time_range` | 按时间范围搜索会议内容 |
| `get_topic_history` | 追踪某个主题、项目、客户或问题的历史讨论 |
| `generate_weekly_report` | 生成周报素材 |
| `web_search` | 使用 Tavily 搜索外部信息 |

## 项目结构

```text
app/
  agent/          Agent 循环、工具、校验、任务
  memory/         user_profile、reflection、feedback reflection
  extract/        会议结构化抽取
  embed/          向量索引
  ingest/         会议导入
  llm/            大模型接口封装
  qa/             基础检索问答
  storage/        SQLite schema 和连接

frontend/         前端界面
scripts/          离线导入、抽取、索引、记忆管理脚本
training_loop/    独立训练闭环工具
docs/             设计文档
data/             SQLite、Chroma、训练导出产物
```

## 私有化部署说明

所有大模型请求集中在：

```text
app/llm/client.py
```

如果私有模型服务兼容 OpenAI Chat Completions，通常只需要修改 `.env`：

```env
APIFUSION_API_URL=http://your-private-llm/v1/chat/completions
APIFUSION_API_KEY=your_private_key
APIFUSION_MODEL=your_model
```

私有模型需要重点支持：

- 普通 chat
- JSON 输出
- tool calling/function calling
- 流式输出

如果私有模型不支持原生 tool calling，需要改造 `chat_with_tools()` 和 `chat_with_tools_stream()`，让模型输出可解析的工具调用 JSON。

## 开发校验

后端语法检查：

```bash
python -m py_compile app\config.py app\main.py app\agent\loop.py
```

前端构建：

```bash
cd frontend
npm run build
```

训练闭环工具检查：

```bash
python -m py_compile training_loop\common.py training_loop\review_samples.py training_loop\export_datasets.py
```
