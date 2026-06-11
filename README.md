# MeetAgent

基于本地会议文件的智能问答系统。将会议转写内容导入本地数据库，通过 BM25 检索相关片段，结合大模型回答自然语言问题，答案附带来源引用；同时支持对每场会议离线抽取结构化记忆（摘要、待办、决策、风险、实体）。

---

## 快速开始

### 1. 环境准备

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
EXTRACT_WINDOW_CHARS=6000             # 结构化抽取每窗口字数
EXTRACT_CONCURRENCY=5                 # 抽取并发数
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

### 6. 问答

**CLI：**

```bash
# 提问（全局）
python -m app.qa.ask "爆品战略主要讲了什么？"

# 限定某个用户的会议
python -m app.qa.ask "有哪些待办事项？" <user_id>
```

**启动 HTTP 服务：**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问 `http://localhost:8000/docs` 查看交互式 API 文档。

主要接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/qa` | 问答，返回答案和引用来源 |
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
    llm/client.py          # 大模型调用封装（支持 chat / chat_json）
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
      ask.py               # CLI 问答入口
      service.py           # 问答服务
      prompts.py           # 问答 prompt 模板
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
- [ ] 阶段四：工具调用与 Agent 化

