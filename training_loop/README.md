# MeetAgent Training Loop

Language: [English](README.md) | [中文](README.zh-CN.md)

This directory is intentionally separated from the runtime `app/` code. It reads
the existing SQLite database and produces review/export artifacts for offline
training.

## Goal

Build a controlled loop:

```text
online QA -> agent_eval_samples -> review -> JSONL exports -> fine-tuning -> benchmark -> deploy decision
```

The current project should not train directly from raw database tables. Use this
directory to filter and version training candidates.

## Data Sources

- `agent_eval_samples`: primary source for tool-call, answer-generation, and
  preference training candidates.
- `chat_messages`: useful for debugging and future feedback-pair mining, but not
  exported directly by default.
- `memories`: stores `preference:user_profile` and `reflection:*`; useful for
  prompts and reflection training, not for factual QA training.
- `meetings/chunks/meeting_summaries/action_items/decisions/risks`: RAG corpus,
  not direct agent-behavior training data.

## Workflow

1. Inspect sample pool:

```powershell
python training_loop/review_samples.py summary
python training_loop/review_samples.py list --limit 20
python training_loop/review_samples.py show <sample_id>
```

2. Review samples:

```powershell
python training_loop/review_samples.py mark <sample_id> --status accepted
python training_loop/review_samples.py mark <sample_id> --status rejected
python training_loop/review_samples.py mark <sample_id> --status fixed
```

3. Export reviewed datasets:

```powershell
python training_loop/export_datasets.py --type all --review-status accepted --passed-only
python training_loop/export_datasets.py --type tool_call --output data/training/tool_call.jsonl
python training_loop/export_datasets.py --type answer_generation --output data/training/answer_generation.jsonl
python training_loop/export_datasets.py --type preference --output data/training/preference.jsonl
```

4. Maintain a fixed benchmark set:

```text
training_loop/benchmarks/meeting_agent_eval.example.jsonl
```

Copy it to a real benchmark file and fill expected tool calls, answer points, and
source requirements before comparing models.

## Export Types

### `tool_call`

Use for SFT of tool selection and tool arguments.

### `answer_generation`

Use for SFT of grounded answers from question + tool results + sources.

### `preference`

Use for DPO-style chosen/rejected pairs when a draft answer was rewritten or
manually fixed.

## Private Deployment Notes

Private model replacement should first target:

1. tool calling behavior;
2. grounded answer generation;
3. verifier/judge;
4. reflection generation.

Keep RAG corpus data separate from training data.
