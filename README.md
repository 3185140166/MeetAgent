# MeetAgent

基于本地会议文件的智能问答系统。将会议转写内容导入本地数据库，通过 BM25 检索相关片段，结合大模型回答自然语言问题，答案附带来源引用。

## 环境准备

**1. 创建虚拟环境**

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

**2. 安装依赖**

```bash
pip install -r requirements.txt
```

**3. 配置环境变量**

复制 `.env.example` 为 `.env`，填入 API Key：

```bash
cp .env.example .env
```

```env
APIFUSION_API_URL=https://apifusion.aispeech.com.cn/v1/chat/completions
APIFUSION_API_KEY=your_api_key_here
APIFUSION_MODEL=gpt-5.5
DB_PATH=data/meetagent.db
TOP_K=8
```

## 使用方法

**导入会议数据**

将会议 JSON 文件放入 `test_meetingdata/`，然后运行：

```bash
python -m app.ingest.import_meetings test_meetingdata
```

重复执行是安全的，已导入的会议会自动跳过。

**提问**

```bash
python -m app.qa.ask "爆品战略主要讲了什么？"
```

返回结果包含答案和引用来源（会议标题、时间、发言人、片段编号）。

## 项目结构

```
MeetAgent/
  app/
    config.py              # 环境变量配置
    main.py                # FastAPI 服务入口
    llm/client.py          # 大模型调用封装
    storage/
      schema.sql           # 数据库表结构
      db.py                # 数据库连接
    ingest/
      import_meetings.py   # 会议数据导入
      chunker.py           # 文本切分 + jieba 分词
    search/bm25.py         # BM25 检索
    qa/
      ask.py               # CLI 问答入口
      service.py           # 问答服务
      prompts.py           # Prompt 模板
  data/
    meetagent.db           # SQLite 数据库（自动生成）
    stopwords.txt          # jieba 停用词
    course_keywords.txt    # 领域关键词
  test_meetingdata/        # 会议 JSON 原始数据
  docs/
    meeting_agent_plan.md  # 项目设计文档
```

## 数据说明

会议 JSON 文件格式：每个文件对应一个用户的一批会议记录，包含 `note_id`、`title`、`create_time`、`asr_segment`（转写片段列表）等字段。

## 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问 `http://localhost:8000/docs` 可查看交互式 API 文档。

## 开发阶段

- [x] 阶段一：本地会议问答（BM25 + 大模型）
- [ ] 阶段二：结构化会议记忆（摘要、待办、决策抽取）
- [ ] 阶段三：混合检索（BM25 + 向量检索 + rerank）
- [ ] 阶段四：工具调用与 Agent 化
