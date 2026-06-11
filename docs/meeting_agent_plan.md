# 会议智能问答 Agent 项目计划

## 1. 项目定位

本项目第一阶段不做完整的通用 Agent，也不优先做自动入会、实时录音、实时转写等能力。

第一阶段目标是：

> 基于本地会议文件，构建一个可检索、可追问、答案可追溯的会议智能问答系统。

用户每次开完会后，设备或云端会产生会议资产，例如：

- 录音文件
- 转写文本
- 会议纪要
- 洞察信息
- 待办事项
- 附件文档

本项目先从已有会议 JSON 数据出发，完成：

- 会议数据导入
- 本地结构化存储
- BM25 检索
- 大模型问答
- 引用来源返回

## 2. 第一阶段 MVP 范围

第一版只解决一个核心问题：

> 用户提出自然语言问题，系统能从历史会议内容中找到相关片段，并让大模型基于这些片段回答。

示例问题：

- 上次关于爆品战略主要讲了什么？
- 某个客户提出过哪些需求？
- 这几次会议里有哪些待办？
- 谁提到了预算风险？
- 某个主题之前有没有讨论过？

第一版输出应包含：

- 直接回答
- 相关会议标题
- 会议时间
- 发言人
- 原始片段
- 片段编号或 chunk 编号

第一版暂不做：

- 向量库
- MCP
- 外部工具调用
- 自动创建待办
- 日历集成
- 钉钉/飞书/邮件集成
- 多 Agent 编排
- 权限系统

这些能力放到后续阶段。

## 3. 当前数据基础

当前项目目录中已有测试会议数据：

```text
test_meetingdata/
  1006586430_meetings.json
  1006514828_meetings.json
  ...
```

每个 JSON 文件对应一个用户的一批会议记录。

单场会议中比较关键的字段包括：

```text
note_id
userid
title
create_time
duration_minutes
language
audio_id
audio_full_path
asr_result_length
asr_segment
```

`asr_segment` 是会议转写片段列表，目前每个片段主要包含：

```text
speaker
text
```

当前数据暂未看到稳定的时间戳字段，所以第一版先基于会议、发言人和 chunk 编号做引用。后续如果数据中补充 `start_time` / `end_time`，再支持跳转到音频或视频时间点。

## 4. 技术路线

第一阶段推荐技术路线：

```text
本地会议 JSON 文件
        |
        v
导入脚本 ingest
        |
        v
SQLite
  - meetings
  - chunks
  - fts_chunks
        |
        v
BM25 检索
        |
        v
Prompt 组装
        |
        v
大模型回答
        |
        v
答案 + 引用来源
```

选择 SQLite + BM25 的原因：

- 部署简单
- 不依赖外部数据库
- 适合本地 MVP
- 方便快速验证产品价值
- 后续可平滑迁移到 PostgreSQL、pgvector 或 Elasticsearch

## 5. 数据库存储设计

第一版使用 SQLite。

建议数据库文件路径：

```text
data/meetagent.db
```

### 5.1 meetings 表

存储会议元信息。

```sql
CREATE TABLE IF NOT EXISTS meetings (
  note_id TEXT PRIMARY KEY,
  user_id TEXT,
  title TEXT,
  create_time TEXT,
  duration_minutes REAL,
  language TEXT,
  audio_id TEXT,
  audio_path TEXT,
  raw_json_path TEXT,
  asr_result_length INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 chunks 表

存储切分后的会议文本片段。

```sql
CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  note_id TEXT NOT NULL,
  user_id TEXT,
  chunk_index INTEGER NOT NULL,
  speaker TEXT,
  text TEXT NOT NULL,
  search_text TEXT NOT NULL,
  char_count INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(note_id) REFERENCES meetings(note_id)
);
```

### 5.3 fts_chunks 表

使用 SQLite FTS5 建全文索引。

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
  chunk_id UNINDEXED,
  note_id UNINDEXED,
  user_id UNINDEXED,
  search_text
);
```

## 6. 中文 BM25 检索策略

SQLite FTS5 默认对中文支持有限。第一版建议导入前做中文分词。

推荐方案：

- 使用 `jieba` 对会议文本分词
- 分词结果用空格拼接后写入 `search_text`
- 用户 query 也先经过同样分词
- FTS5 对 `search_text` 做 BM25 检索

示例：

```text
原文：
今天我们讨论超级爆品战略

search_text：
今天 我们 讨论 超级 爆品 战略
```

如果暂时不想引入 `jieba`，也可以先用 SQLite FTS5 的 `unicode61` tokenizer 跑通流程，但中文召回效果可能不稳定。

## 7. Chunk 切分策略

第一版不建议一条 `asr_segment` 就作为一个 chunk，也不建议整场会议作为一个 chunk。

推荐策略：

- 按 `asr_segment` 原顺序累计文本
- 每个 chunk 控制在 800-1500 个中文字左右
- chunk 之间可以保留 100-200 字 overlap
- 保留 speaker 信息
- 保留 chunk_index

切分后的 chunk 示例：

```json
{
  "chunk_id": "note_id:00012",
  "note_id": "xxx",
  "user_id": "1006514828",
  "chunk_index": 12,
  "speaker": "1,2",
  "text": "原始会议片段文本...",
  "search_text": "分词 后 的 检索 文本"
}
```

## 8. 问答流程

完整问答流程：

```text
用户问题
  -> query 分词
  -> FTS5 BM25 检索 top_k chunks
  -> 取 top 5-8 个高相关片段
  -> 组装 prompt
  -> 调用大模型
  -> 返回答案和引用
```

### 8.1 检索 SQL 示例

```sql
SELECT
  f.chunk_id,
  f.note_id,
  f.user_id,
  bm25(fts_chunks) AS score,
  c.chunk_index,
  c.speaker,
  c.text,
  m.title,
  m.create_time
FROM fts_chunks f
JOIN chunks c ON c.chunk_id = f.chunk_id
JOIN meetings m ON m.note_id = f.note_id
WHERE fts_chunks MATCH ?
ORDER BY score
LIMIT ?;
```

### 8.2 Prompt 约束

问答 prompt 必须要求模型只基于检索片段回答。

建议系统提示词：

```text
你是一个会议智能问答助手。
你只能基于用户提供的会议片段回答问题。
如果会议片段中没有足够依据，请明确说“当前会议资料中没有找到明确依据”。
不要编造会议中没有出现的信息。
回答后必须列出引用来源，包括会议标题、会议时间、发言人和片段编号。
```

## 9. 大模型调用方式

当前项目中的 `reponse.py` 不纳入正式项目结构，但可以参考它的大模型调用方式。

当前可用的大模型接口地址是：

```text
https://apifusion.aispeech.com.cn/v1/chat/completions
```

正式项目中建议将大模型调用封装为独立模块：

```text
app/llm/client.py
```

不要把 API Key 写入代码或文档。建议使用环境变量：

```text
APIFUSION_API_KEY
```

推荐配置项：

```text
APIFUSION_API_URL=https://apifusion.aispeech.com.cn/v1/chat/completions
APIFUSION_API_KEY=从环境变量读取
APIFUSION_MODEL=gpt-5.5
```

### 9.1 为什么建议异步调用

正式服务中建议使用异步 HTTP 调用大模型，因为：

- 大模型请求耗时较长
- API 服务不能因为一个请求阻塞整个 worker
- 后续可能需要并发处理多个用户问题
- 后续可能会同时做摘要、结构化抽取和问答

推荐使用：

```text
httpx.AsyncClient
```

接口形态可以设计为：

```python
async def chat(messages: list[dict], temperature: float = 0.2) -> str:
    ...
```

CLI 调试时可以额外提供同步包装：

```python
def chat_sync(prompt: str) -> str:
    ...
```

## 10. 推荐项目目录

建议第一阶段目录结构：

```text
MeetAgent/
  app/
    __init__.py
    config.py
    main.py
    llm/
      __init__.py
      client.py
    storage/
      __init__.py
      db.py
      schema.sql
    ingest/
      __init__.py
      import_meetings.py
      chunker.py
    search/
      __init__.py
      bm25.py
    qa/
      __init__.py
      ask.py
      prompts.py
      service.py
  data/
    meetagent.db
  tests/
    test_ingest.py
    test_search.py
    test_qa.py
  docs/
    meeting_agent_plan.md
  test_meetingdata/
  requirements.txt
  .env.example
  .gitignore
```

说明：

- `ingest/`：负责把会议 JSON 导入 SQLite
- `search/`：负责 BM25 检索
- `qa/`：负责检索增强问答
- `llm/`：负责大模型接口调用
- `storage/`：负责数据库连接和表结构
- `main.py`：后续提供 FastAPI 服务入口

## 11. 第一阶段开发任务拆解

### 任务 1：初始化项目结构

创建基础目录：

```text
app/
data/
docs/
```

创建 Python 包：

```text
app/__init__.py
app/llm/__init__.py
app/storage/__init__.py
app/ingest/__init__.py
app/search/__init__.py
app/qa/__init__.py
```

### 任务 2：数据库初始化

实现：

```text
app/storage/schema.sql
app/storage/db.py
```

支持：

- 创建 SQLite 连接
- 初始化表结构
- 重建索引

### 任务 3：会议数据导入

实现：

```text
app/ingest/import_meetings.py
app/ingest/chunker.py
```

功能：

- 扫描 `test_meetingdata/*.json`
- 读取每个用户的会议列表
- 写入 `meetings`
- 将 `asr_segment` 切分为 chunks
- 写入 `chunks`
- 写入 `fts_chunks`

命令示例：

```bash
python -m app.ingest.import_meetings test_meetingdata
```

### 任务 4：BM25 检索

实现：

```text
app/search/bm25.py
```

功能：

- 输入 query
- 返回 top_k 会议片段
- 支持按 `user_id` 过滤
- 返回会议标题、时间、speaker、chunk_index、原文

### 任务 5：大模型 Client

实现：

```text
app/llm/client.py
```

功能：

- 从环境变量读取 API URL、API Key、模型名
- 使用异步 HTTP 请求
- 封装 OpenAI-compatible chat completions 接口
- 统一错误处理和超时

### 任务 6：会议问答服务

实现：

```text
app/qa/service.py
app/qa/prompts.py
app/qa/ask.py
```

功能：

- 接收用户问题
- 调用 BM25 检索
- 组装上下文
- 调用大模型
- 返回答案和引用

命令示例：

```bash
python -m app.qa.ask "爆品战略主要讲了什么？"
```

### 任务 7：FastAPI 服务

在 CLI 跑通后，再实现：

```text
app/main.py
```

建议接口：

```text
POST /qa
GET /meetings
GET /meetings/{note_id}
GET /chunks/{chunk_id}
```

`POST /qa` 请求示例：

```json
{
  "question": "爆品战略主要讲了什么？",
  "user_id": "1006514828",
  "top_k": 8
}
```

响应示例：

```json
{
  "answer": "根据会议内容，爆品战略主要强调...",
  "sources": [
    {
      "note_id": "xxx",
      "title": "2025年11月25日 09:00",
      "create_time": "2025-11-25 09:00:27",
      "speaker": "1",
      "chunk_index": 12,
      "text": "原始片段..."
    }
  ]
}
```

## 12. 是否需要 MCP

第一阶段不需要 MCP。

MCP 更适合后续外部工具调用，例如：

- 查询日历
- 读取钉钉文档
- 查询云盘文件
- 创建待办
- 发送钉钉消息
- 查询企业通讯录

当前第一阶段的核心是：

```text
会议文件 -> 本地存储 -> 本地检索 -> 大模型问答
```

这不需要 MCP。

建议顺序：

```text
第 1 阶段：本地会议问答
第 2 阶段：会议结构化记忆
第 3 阶段：外部工具集成
第 4 阶段：MCP / tools / Agent 编排
```

## 13. 后续阶段规划

### 第二阶段：结构化会议记忆

对每场会议离线抽取：

- 摘要
- 议题
- 决策
- 待办
- 风险
- 关键问题
- 相关人物
- 相关项目
- 相关客户
- 相关产品

新增表：

```text
meeting_summaries
action_items
decisions
risks
entities
facts
```

### 第三阶段：混合检索

在 BM25 基础上加入向量检索：

```text
BM25 关键词召回
      +
向量语义召回
      +
重排序 rerank
```

可选技术：

- pgvector
- Qdrant
- Milvus
- Elasticsearch

### 第四阶段：工具调用和 Agent 化

当系统具备稳定问答和记忆后，再引入 Agent 能力：

- 自动生成待办
- 同步到钉钉/飞书
- 读取日历上下文
- 生成会前准备材料
- 跟踪历史决策
- 主动提醒未完成事项

这时再考虑 MCP 或工具层设计。

## 14. 第一版成功标准

第一阶段完成后，系统应满足：

- 能导入 `test_meetingdata/*.json`
- 能把会议转写切分成可检索 chunks
- 能用 BM25 检索相关会议片段
- 能调用大模型回答用户问题
- 回答严格基于检索片段
- 回答中包含引用来源
- 能通过 CLI 完成完整问答流程

最小可验收命令：

```bash
python -m app.ingest.import_meetings test_meetingdata
python -m app.qa.ask "爆品战略主要讲了什么？"
```

如果这两个命令能跑通，并且答案带来源引用，就说明第一版 MVP 成立。
