# MeetAgent 训练闭环

语言：[English](README.md) | [中文](README.zh-CN.md)

这个目录和运行时 `app/` 代码刻意分离。它只读取现有 SQLite 数据库，生成离线审核、导出和评测相关产物，不接入 FastAPI，也不影响线上 Agent 问答链路。

## 目标

构建一个可控训练闭环：

```text
线上问答 -> agent_eval_samples -> 人工审核 -> JSONL 导出 -> 微调训练 -> 固定评测 -> 上线决策
```

当前项目不应该直接拿原始数据库表训练。应该先通过这个目录筛选、审核、版本化训练候选样本。

## 数据来源

- `agent_eval_samples`：最主要的数据来源，用于工具调用、回答生成、偏好训练候选。
- `chat_messages`：适合调试和未来挖掘用户反馈样本，默认不直接导出训练。
- `memories`：只存 `preference:user_profile` 和 `reflection:*`，适合提示词增强和反思训练，不适合作为事实问答训练数据。
- `meetings/chunks/meeting_summaries/action_items/decisions/risks`：RAG 知识库语料，不是直接的 Agent 行为训练数据。

## 使用流程

1. 查看样本池：

```powershell
python training_loop/review_samples.py summary
python training_loop/review_samples.py list --limit 20
python training_loop/review_samples.py show <sample_id>
```

2. 人工审核样本：

```powershell
python training_loop/review_samples.py mark <sample_id> --status accepted
python training_loop/review_samples.py mark <sample_id> --status rejected
python training_loop/review_samples.py mark <sample_id> --status fixed
```

状态含义：

```text
pending   待审核
accepted  可直接进入训练集
rejected  不进入训练集
fixed     人工修正后可进入训练集
```

3. 导出已审核数据集：

```powershell
python training_loop/export_datasets.py --type all --review-status accepted --passed-only
python training_loop/export_datasets.py --type tool_call --output data/training/tool_call.jsonl
python training_loop/export_datasets.py --type answer_generation --output data/training/answer_generation.jsonl
python training_loop/export_datasets.py --type preference --output data/training/preference.jsonl
```

4. 维护固定评测集：

```text
training_loop/benchmarks/meeting_agent_eval.example.jsonl
```

复制一份作为真实评测集，再补充期望工具调用、答案要点、引用来源要求。训练模型前后都跑同一套评测集，才能判断是否真的变好。

## 导出类型

### `tool_call`

用于训练工具选择和工具参数生成，例如：

```text
用户问题 -> multi_search_meetings / search_meetings / get_topic_history 等工具调用
```

优先级最高，因为工具选择会直接影响召回质量、回答质量和调用轮次。

### `answer_generation`

用于训练基于证据的回答生成：

```text
问题 + 工具结果 + sources -> 带引用、不幻觉、结构清楚的回答
```

### `preference`

用于 DPO/偏好训练：

```text
prompt -> chosen 好答案 / rejected 差答案
```

适合来自 verifier rewrite、人工修正、用户反馈后的样本。

## 私有化训练建议

私有模型替换建议按优先级进行：

1. 工具调用策略；
2. 基于来源的回答生成；
3. verifier / judge；
4. reflection / feedback reflection 生成。

不要把 RAG 语料和训练样本混在一起。会议原文、摘要、待办、决策、风险应该继续作为检索语料；训练数据应该来自经过审核的 Agent 行为样本。

## 当前推荐闭环

```text
1. 线上运行积累 agent_eval_samples
2. 用 review_samples.py 人工审核
3. accepted/fixed 样本进入导出
4. 分别导出 tool_call / answer_generation / preference
5. 用固定 benchmark 做训练前后对比
6. 通过后再替换私有模型或局部模块
```
