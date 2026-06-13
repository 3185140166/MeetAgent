# MeetAgent

基于本地会议文件的智能问答系统。将会议转写内容导入本地数据库，通过 BM25 检索相关片段，结合大模型回答自然语言问题，答案附带来源引用；同时支持对每场会议离线抽取结构化记忆（摘要、待办、决策、风险、实体）。

---

## 快速开始

### 1. 环境准备

推荐使用 Conda（当前项目使用 Python 3.13.13）：

```bash
conda create -n meetagent python=3.13.13
conda activate meetagent
pip install -r requirements.txt
```

如果 Conda 源暂时没有 `3.13.13` 这个精确版本，可先使用可用的 Python 3.13.x：

```bash
conda create -n meetagent python=3.13
conda activate meetagent
pip install -r requirements.txt
```

也可以使用 Python 自带 venv：

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入 API Key：

```bash
cp .env.example .env
```

`.env` 说明：

```env
APIFUSION_API_URL=https://apifusion.aispeech.com.cn/v1/chat/completions
APIFUSION_API_KEY=your_api_key_here   # 必填
APIFUSION_MODEL=gpt-5.5
DB_PATH=data/meetagent.db
TOP_K=8                               # 问答检索片段数
ENABLE_HYBRID_SEARCH=false            # 默认关闭向量混合检索，避免模型未就绪时自动下载
EXTRACT_WINDOW_CHARS=6000             # 结构化抽取每窗口字数
EXTRACT_CONCURRENCY=5                 # 抽取并发数
TAVILY_API_KEY=your_tavily_key_here   # 可选，启用联网搜索工具
WEB_SEARCH_MAX_RESULTS=5              # 联网搜索默认结果数
```

### 3. 导入会议数据

将会议 JSON 文件放入 `test_meetingdata/`，运行导入脚本：

```bash
python -m app.ingest.import_meetings test_meetingdata
```

重复执行安全，已导入的会议自动跳过。

### 4. 结构化记忆抽取（可选）

导入后可对会议做离线结构化抽取，提取摘要、待办、决策、风险、实体：

```bash
# 查看各用户抽取进度
python scripts/stats.py

# 对指定用户抽取前 N 场（按时间升序，剩余留作增量测试）
python scripts/extract_user.py --user-id <user_id> --limit 25

# 先确认待处理数量，不实际执行
python scripts/extract_user.py --user-id <user_id> --dry-run
```

### 5. 构建向量索引（可选，启用混合检索）

使用本地 `BAAI/bge-small-zh-v1.5` 模型（约 90MB，CPU 可运行）对所有 chunks 做向量编码，写入 ChromaDB：

```bash
# 对指定用户构建向量索引
python scripts/build_index.py --user-id <user_id>

# 全量构建（所有用户）
python scripts/build_index.py

# 自定义批大小（默认 128，内存紧张可调小）
python scripts/build_index.py --user-id <user_id> --batch-size 64
```

索引保存在 `data/chroma/`，构建完成后问答自动切换为**混合检索模式**（BM25 + 向量 + RRF 融合）。

> 首次运行会自动下载 embedding 模型到 `models/` 目录（需要联网），之后离线可用。

Embedding 配置含义：

```env
EMBED_PROVIDER=local
EMBED_LOCAL_MODEL=models/BAAI/bge-small-zh-v1.5
EMBED_MODEL_DIR=models
EMBED_DIM=512
```

- `EMBED_PROVIDER=local`：使用本地 `sentence-transformers` 加载模型。
- `EMBED_PROVIDER=dashscope`：使用 DashScope embedding API，不加载本地模型。
- `EMBED_LOCAL_MODEL`：当 provider 为 `local` 时使用。可以是本地模型目录，也可以是 Hugging Face 模型名；如果写成本地目录，例如 `models/BAAI/bge-small-zh-v1.5`，就会直接从该目录加载。
- `EMBED_MODEL_DIR`：传给 `sentence-transformers` 的缓存目录。它不是具体模型路径；只有当 `EMBED_LOCAL_MODEL` 写成 Hugging Face 模型名时，才会作为下载/缓存目录使用。

如果本地 embedding 模型尚未完整下载，建议保持：

```env
ENABLE_HYBRID_SEARCH=false
```

此时系统只使用 BM25，不会在普通问答时自动连接 Hugging Face。模型和向量索引准备好后，再改为：

```env
ENABLE_HYBRID_SEARCH=true
```

### 6. 问答

系统提供两种问答模式：

**模式 A：检索问答（Phase 1-3）**
直接用混合检索找相关原文片段，交给 LLM 回答。适合查具体发言内容。

```bash
python -m app.qa.ask "爆品战略主要讲了什么？"
python -m app.qa.ask "有哪些待办事项？" <user_id>
```

**模式 B：Agent 单次问答（Phase 4）**
LLM 自主决定调用哪些工具（结构化查询 / 原文检索），支持更复杂的问题。
Agent 默认最多进行 10 轮工具调用；如果信息已足够，会提前结束并回答，不会强制跑满 10 轮。HTTP 接口会将 `max_turns` 限制在 1-20 之间。

```bash
python -m app.agent.ask "我有哪些待办事项？" <user_id>
python -m app.agent.ask "最近的会议有哪些主要风险？" <user_id>
python -m app.agent.ask "上周做了哪些决策？" <user_id>
```

**模式 C：Agent 多轮对话（Phase 5A）**
保持会话历史，支持追问和上下文引用。输入 `clear` 清空历史，`exit` 退出。

```bash
python -m app.agent.chat <user_id>
```

示例对话：
```
你：最近有哪些风险？
助手：共找到 X 条风险：...

你：第一条具体是什么情况？
助手：（基于上轮结果继续回答，无需重新检索）
```

Agent 可调用的工具：

| 工具 | 作用 |
|------|------|
| `search_meetings` | 混合检索会议原文片段 |
| `get_action_items` | 查询结构化待办事项 |
| `get_decisions` | 查询决策记录 |
| `get_risks` | 查询风险项 |
| `get_meeting_summary` | 获取某场会议摘要 |
| `list_meetings` | 列出会议清单 |
| `get_meeting_detail` | 获取某场会议详情、结构化记忆和部分原文片段 |
| `search_by_time_range` | 按时间范围搜索会议内容 |
| `get_topic_history` | 追踪某个主题、项目、客户或问题的历史讨论 |
| `generate_weekly_report` | 基于会议摘要、待办、决策和风险生成周报素材 |
| `web_search` | 使用 Tavily 联网搜索外部信息，回答时附 URL 来源 |

启用联网搜索需要在 `.env` 中配置 Tavily：

```env
TAVILY_API_KEY=your_tavily_key_here
TAVILY_API_URL=https://api.tavily.com/search
WEB_SEARCH_MAX_RESULTS=5
```

**启动 HTTP 服务：**

如果使用 Conda 环境，先激活环境：

```bash
conda activate meetagent
```

然后在项目根目录启动后端：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问 `http://localhost:8000/docs` 查看交互式 API 文档。

**启动前端：**

另开一个终端，进入前端目录安装依赖并启动 Vite：

```bash
cd frontend
npm install
npm run dev
```

默认访问地址：

```text
http://localhost:5173
```

数据概览 / 管理页：

```text
http://localhost:5173/admin
```

管理页可查看全局数据、用户列表、用户会议列表、会话列表和会话消息。聊天会话会持久化到 SQLite 的 `chat_sessions` / `chat_messages` 表，不再按固定时间自动清理；后续如需“短期记忆 / 长期记忆”，应单独生成结构化记忆产物，而不是依赖聊天 session 过期逻辑。

打开前端后，左侧“用户 ID”可以填写要查询的用户。测试数据中可先使用：

```text
1006734045
```

如果用户 ID 留空，则按全局数据查询，不做用户过滤。

前端默认请求后端 `http://localhost:8000`。如需修改后端地址，可在 `frontend/.env` 中设置：

```env
VITE_API_BASE=http://localhost:8000
```

主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/qa` | 检索问答（Phase 1-3），返回答案和引用来源 |
| POST | `/agent/qa` | Agent 问答（Phase 4），返回答案和工具调用日志 |
| GET  | `/stats` | 全局数据统计，用于数据概览页 |
| GET  | `/users` | 用户数据概览列表 |
| GET  | `/users/{user_id}/meetings` | 指定用户的会议列表 |
| GET  | `/sessions` | 会话列表，用于管理页查看聊天记录 |
| GET  | `/meetings` | 会议列表，支持 `?user_id=` 过滤 |
| GET  | `/meetings/{note_id}` | 单场会议详情 |
| GET  | `/chunks/{chunk_id}` | 单个文本片段 |

---

## 数据格式

系统读取 JSON 文件，每个文件包含**一个用户的多场会议**，顶层为数组。

**实际用到的字段（最小必要集）：**

```json
[
  {
    "note_id": "唯一会议 ID（字符串，必填）",
    "userid": "用户 ID（字符串，必填）",
    "title": "会议标题（字符串）",
    "create_time": "创建时间，格式 YYYY-MM-DD HH:MM:SS",
    "duration_minutes": 90.5,
    "language": "cn",
    "audio_id": "音频文件 ID（可选）",
    "audio_full_path": "音频文件路径（可选）",
    "asr_result_length": 12345,
    "asr_segment": [
      { "speaker": "1", "text": "发言人1的转写文本" },
      { "speaker": "2", "text": "发言人2的转写文本" }
    ]
  }
]
```

**适配其他格式说明：**

| 字段 | 是否必填 | 说明 |
|------|----------|------|
| `note_id` | ✅ 必填 | 用作主键，需全局唯一 |
| `userid` | ✅ 必填 | 用于用户隔离和权限过滤 |
| `asr_segment` | ✅ 必填 | 转写片段数组，每项需有 `text` 字段；`speaker` 可为空字符串 |
| `title` | 建议填 | 问答引用来源展示用 |
| `create_time` | 建议填 | 排序和时间过滤用 |
| 其余字段 | 可选 | 缺失时写入空值，不影响核心功能 |

如果你的数据字段名不同（如 `meeting_id` 而非 `note_id`），在 `app/ingest/import_meetings.py` 中修改对应的 `meeting.get("字段名")` 即可。

---

## 工具脚本

| 脚本 | 说明 |
|------|------|
| `scripts/stats.py` | 查看所有用户的会议数量和抽取进度 |
| `scripts/extract_user.py` | 对指定用户做结构化记忆抽取 |
| `scripts/show_memory.py` | 查看指定用户或会议的结构化记忆内容 |
| `scripts/build_index.py` | 构建向量索引（BM25 + 向量混合检索前置步骤） |

```bash
# 查看某用户所有会议摘要
python scripts/show_memory.py --user-id <user_id>

# 查看某场会议的完整结构化记忆
python scripts/show_memory.py --note-id <note_id>

# 只看待办事项
python scripts/show_memory.py --user-id <user_id> --type action_items
```

---

## 项目结构

```
MeetAgent/
  app/
    config.py              # 环境变量配置
    main.py                # FastAPI 服务入口
    llm/client.py          # 大模型调用封装（chat / chat_json / chat_with_tools）
    storage/
      schema.sql           # 数据库表结构
      db.py                # 数据库连接
    ingest/
      import_meetings.py   # 会议数据导入（幂等）
      chunker.py           # 文本切分 + jieba 分词
    search/
      bm25.py              # BM25 检索（支持 user_id 过滤）
      hybrid.py            # BM25 + 向量 RRF 混合检索
    embed/
      encoder.py           # 向量编码（本地 bge-small-zh-v1.5 / DashScope API）
      vector_store.py      # ChromaDB 向量库封装
    extract/
      extractor.py         # map-reduce 结构化抽取
      prompts.py           # 抽取 prompt 模板
      run.py               # 抽取 CLI
    qa/
      ask.py               # CLI 问答入口（Phase 1-3，纯检索模式）
      service.py           # 问答服务
      prompts.py           # 问答 prompt 模板
    agent/
      tools.py             # 工具定义（schema + 执行函数）
      loop.py              # Agent 主循环（function calling + 多轮历史）
      ask.py               # 单次问答 CLI（Phase 4）
      chat.py              # 多轮对话 CLI（Phase 5A）
      session.py           # 服务端会话管理（HTTP 用）
  scripts/                 # 运维和调试工具脚本
  data/
    meetagent.db           # SQLite 数据库（自动生成）
    chroma/                # ChromaDB 向量索引（自动生成，不提交 git）
    stopwords.txt          # jieba 停用词
    course_keywords.txt    # 领域关键词
  models/                  # 本地 embedding 模型缓存（自动下载，不提交 git）
  docs/
    meeting_agent_plan.md  # 项目设计文档

```

---

## 开发阶段

- [x] 阶段一：本地会议问答（BM25 + 大模型）
- [x] 阶段二：结构化会议记忆（摘要、待办、决策、风险、实体 map-reduce 抽取）
- [x] 阶段三：混合检索（BM25 + 向量检索 + RRF 融合）
- [x] 阶段四：工具调用与 Agent 化（function calling + 6 个结构化记忆工具）
- [x] 阶段五A：多轮对话（会话历史管理）
- [ ] 阶段五B：跨会议记忆追踪

