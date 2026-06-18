# MeetAgent Algorithm Lab

这个目录用于独立验证和优化 MeetAgent 中的算法模块，不直接修改线上 Agent、前端或数据库写入逻辑。

当前第一版聚焦会议原文检索评测。目标是把“感觉召回更好”变成可量化指标，便于比较 BM25、Hybrid RRF、Multi-query RRF 等方案。

## 目录结构

```text
algorithm_lab/
  datasets/     评测集样例与数据说明
  baselines/    可比较的算法基线
  metrics/      指标计算
  runners/      实验入口脚本
  configs/      实验配置样例
  reports/      实验报告输出目录
```

## 当前支持的检索基线

- `bm25`：复用 `app.search.bm25.search`
- `hybrid_rrf`：复用 `app.search.hybrid.search`，需要向量索引可用
- `multi_query_bm25`：多个 query 分别 BM25 检索后用 RRF 融合
- `multi_query_hybrid`：多个 query 分别 Hybrid 检索后用 RRF 融合，需要向量索引可用

如果向量索引或 embedding 环境不可用，`hybrid_rrf` 和 `multi_query_hybrid` 会失败；这属于实验环境问题，不影响主业务。

## 评测数据格式

JSONL，每行一个样本：

```json
{
  "id": "retrieval_001",
  "user_id": "1006734045",
  "question": "2025年12月22日 11:55 这场会议主要讲了什么？",
  "queries": ["身份定义 经典认同六句话", "2025年12月22日 11:55 身份定义"],
  "relevant_note_ids": ["可选：命中的 note_id"],
  "relevant_chunk_ids": ["可选：命中的 chunk_id"],
  "relevant_keywords": ["身份定义", "经典认同六句话"]
}
```

标注强度从强到弱：

1. `relevant_chunk_ids`：最强，直接验证是否命中证据 chunk。
2. `relevant_note_ids`：中等，验证是否召回正确会议。
3. `relevant_keywords`：较弱，用于没有人工标注证据时的粗略检查。

建议后续逐步把常用问题补成 `relevant_chunk_ids`，这样指标更可信。

## 运行示例

## 环境配置

`algorithm_lab` 默认复用项目根目录 `.env`，因为当前实验代码会调用 `app.search`、`app.embed` 等主项目模块。

如果后续希望算法实验使用独立数据库、独立 embedding/rerank 服务或独立实验参数，可以复制：

```bash
copy algorithm_lab\.env.example algorithm_lab\.env
```

约定：

- `algorithm_lab/.env.example` 可以提交，用于说明可配置项。
- `algorithm_lab/.env` 是本地私有配置，已加入 `.gitignore`，不要提交。
- API Key、私有模型服务地址等敏感信息不要写入 example 文件。
- 非敏感实验参数优先放在 `algorithm_lab/configs/*.json`。
- 本地私有实验配置可命名为 `algorithm_lab/configs/*.local.json`，已加入 `.gitignore`。

```bash
python -m algorithm_lab.runners.run_retrieval_eval \
  --dataset algorithm_lab/datasets/meeting_retrieval_eval.example.jsonl \
  --baseline bm25 \
  --top-k 8
```

多 query：

```bash
python -m algorithm_lab.runners.run_retrieval_eval \
  --dataset algorithm_lab/datasets/meeting_retrieval_eval.example.jsonl \
  --baseline multi_query_bm25 \
  --top-k 8
```

输出 JSON 报告：

```bash
python -m algorithm_lab.runners.run_retrieval_eval \
  --dataset algorithm_lab/datasets/meeting_retrieval_eval.example.jsonl \
  --baseline multi_query_bm25 \
  --top-k 8 \
  --output algorithm_lab/reports/retrieval_multi_query_bm25.json
```

一次比较多个 baseline：

```bash
python -m algorithm_lab.runners.compare_retrieval_baselines \
  --dataset algorithm_lab/datasets/meeting_retrieval_eval.example.jsonl \
  --baselines bm25 multi_query_bm25 \
  --top-k 8
```

## 指标

- `hit_rate@k`：前 k 个结果是否命中任一相关证据。
- `recall@k`：相关 chunk/note 的召回比例。
- `mrr@k`：第一个命中结果的倒数排名。
- `keyword_hit_rate@k`：没有显式证据标注时，结果文本是否覆盖人工关键词。
- `avg_result_count`：平均返回结果数量，用于发现空召回。

## 后续扩展方向

1. 增加向量模型对比：BGE、M3E、Qwen embedding、本地私有 embedding。
2. 增加 reranker：对 top 50 候选进行 cross-encoder 重排。
3. 增加 query 改写策略：人工 query、LLM query、多粒度 query、时间约束 query。
4. 增加工具选择评测：从 `agent_eval_samples` 标注 expected tools。
5. 增加记忆评测：验证 preference/reflection 是否该召回时召回、不该召回时过滤。
