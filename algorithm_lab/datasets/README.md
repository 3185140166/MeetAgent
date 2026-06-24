# Retrieval Datasets

This directory stores algorithm experiment datasets for meeting retrieval.
Use JSONL files for evaluation samples. Do not copy the full meeting corpus
here by default; the source corpus lives in SQLite.

## Dataset Shape

Each retrieval sample is one user question plus labels:

```json
{
  "id": "llm_easy_0001_01",
  "user_id": "1006734045",
  "question": "用户会问的问题",
  "queries": ["可选的检索 query"],
  "relevant_note_ids": ["source note_id"],
  "relevant_chunk_ids": ["source note_id:00020"],
  "relevant_keywords": ["关键词"],
  "difficulty": "easy",
  "review_status": "needs_human_review",
  "source": {
    "note_id": "...",
    "chunk_id": "...",
    "title": "...",
    "create_time": "...",
    "chunk_index": 20,
    "text_preview": "用于出题和审核的片段预览"
  }
}
```

Label strength, from strongest to weakest:

1. `relevant_chunk_ids`: the exact evidence chunks expected to be recalled.
2. `relevant_note_ids`: the meetings expected to be recalled.
3. `relevant_keywords`: weak fallback labels for rough checks.

Evaluation metrics are chunk-strict: `hit_rate`, `recall`, and `mrr` use
`relevant_chunk_ids` only. `relevant_note_ids` are retained for inspection but
do not count as metric hits.

`relevant_chunk_ids` are labels, not the retrieval candidate pool. For this
dataset, the intended candidate pool is all chunks belonging to the user IDs
that appear in the final evaluation file. If `final_100` contains samples from
two users, retrieval should search all chunks for those two users.

## Build Flow

The current LLM-assisted retrieval dataset is built as:

```text
SQLite chunks
-> randomly sample chunks by user and difficulty plan
-> ask an LLM to generate a natural user question from each chunk
-> store the sampled chunk as relevant_chunk_ids
-> auto-review with a stricter LLM
-> human-review the accepted/revised/rejected output
-> export only accepted samples into a final eval JSONL
-> run retrieval metrics against SQLite or a fixed corpus snapshot
```

The single-evidence `final_100` set is built from one source chunk per question.
It is best for Chunk Hit@K and Chunk MRR@K. Since most rows have exactly one
`relevant_chunk_id`, Recall@K is usually equivalent to Hit@K.

Draft generation:

```bash
python -m algorithm_lab.runners.build_retrieval_dataset \
  --mode llm \
  --user-id 1006734045 \
  --user-id 1006760747 \
  --difficulty-plan easy:50,medium:60,hard:30 \
  --queries-per-chunk 1 \
  --output algorithm_lab/datasets/meeting_retrieval_eval.llm_draft_140.jsonl
```

Automatic review and repair:

```bash
python -m algorithm_lab.runners.auto_review_retrieval_dataset \
  --input algorithm_lab/datasets/meeting_retrieval_eval.llm_draft_140.jsonl \
  --output algorithm_lab/datasets/meeting_retrieval_eval.auto_reviewed_140.jsonl \
  --review-model deepseek-v4-pro-max
```

Manual review should use the auto-reviewed file as input:

```bash
python -m algorithm_lab.scripts.review_retrieval_dataset \
  --input algorithm_lab/datasets/meeting_retrieval_eval.auto_reviewed_140.jsonl \
  --output algorithm_lab/datasets/meeting_retrieval_eval.review_work.jsonl
```

The manual UI shows the model's status, confidence, reason, original question,
and rewritten question/keywords where available. Prioritize reviewing:

- `auto_review_status=revised`
- `auto_review_status=rejected`
- low-confidence `auto_review_status=accepted`
- samples whose source chunk is only related but cannot directly answer the question

After manual review, export a final dataset:

```bash
python -m algorithm_lab.runners.export_reviewed_retrieval_dataset \
  --input algorithm_lab/datasets/meeting_retrieval_eval.review_work.jsonl \
  --output algorithm_lab/datasets/meeting_retrieval_eval.final.jsonl
```

By default this exports only:

```text
review_status = reviewed
```

For a larger working eval set, include model-accepted samples and cap the final
file to 100 rows. The exporter prioritizes manually `reviewed` rows first, then
fills the remaining slots from `auto_accepted` rows:

```bash
python -m algorithm_lab.runners.export_reviewed_retrieval_dataset \
  --input algorithm_lab/datasets/meeting_retrieval_eval.review_work.jsonl \
  --output algorithm_lab/datasets/meeting_retrieval_eval.final_100.jsonl \
  --include-auto-accepted \
  --limit 100 \
  --difficulty-plan easy:30,medium:50,hard:20
```

If `--difficulty-plan` is omitted with `--limit 100`, the default is also close
to a 30/50/20 easy/medium/hard split.

## Multi-Evidence Set

Build a separate multi-evidence draft when you want Recall@K to be meaningful.
This script samples adjacent chunks from the same meeting, asks the LLM to write
one question that requires at least two chunks, and stores every source chunk in
`relevant_chunk_ids`.

```bash
python -m algorithm_lab.runners.build_multi_evidence_dataset \
  --user-id 1006734045 \
  --user-id 1006760747 \
  --target-count 50 \
  --window-size 3 \
  --output algorithm_lab/datasets/meeting_retrieval_eval.multi_evidence_draft_50.jsonl
```

Output rows follow the same top-level shape as `meeting_retrieval_eval.final_100.jsonl`.
The difference is that `relevant_chunk_ids` contains multiple chunks, and
`source.chunks` plus `source.evidence_requirements` preserve the evidence map
for review.

Review requirements for multi-evidence rows are stricter:

- At least two source chunks must be necessary to answer the question.
- Each `relevant_chunk_id` should contribute a distinct required fact.
- Reject or rewrite rows that can be answered from only one chunk.
- Keep this dataset separate from `final_100`; use it for Recall@K-focused evaluation.

After review, export the accepted rows to a final file, for example:

```bash
python -m algorithm_lab.runners.export_reviewed_retrieval_dataset \
  --input algorithm_lab/datasets/meeting_retrieval_eval.multi_evidence_review_work.jsonl \
  --output algorithm_lab/datasets/meeting_retrieval_eval.multi_evidence_final_50.jsonl
```

Evaluate it with the same runner:

```bash
python -m algorithm_lab.runners.compare_retrieval_baselines \
  --dataset algorithm_lab/datasets/meeting_retrieval_eval.multi_evidence_final_50.jsonl \
  --baselines bm25 llm_sparse_bm25 dense hybrid_rrf \
  --top-k 8 \
  --user-scope dataset
```

Formal high-confidence metrics should use the manually confirmed final file:

```bash
python -m algorithm_lab.runners.run_retrieval_eval \
  --dataset algorithm_lab/datasets/meeting_retrieval_eval.final.jsonl \
  --baseline bm25 \
  --top-k 8 \
  --user-scope dataset
```

For the 100-row working eval set:

```bash
python -m algorithm_lab.runners.run_retrieval_eval \
  --dataset algorithm_lab/datasets/meeting_retrieval_eval.final_100.jsonl \
  --baseline bm25 \
  --top-k 8 \
  --user-scope dataset \
  --output algorithm_lab/reports/retrieval_bm25_final_100_dataset_scope.json
```

Compare multiple baselines with the same corpus scope:

```bash
python -m algorithm_lab.runners.compare_retrieval_baselines \
  --dataset algorithm_lab/datasets/meeting_retrieval_eval.final_100.jsonl \
  --baselines bm25 llm_sparse_bm25 dense hybrid_rrf \
  --top-k 8 \
  --user-scope dataset
```

Baseline meanings:

- `bm25`: original query -> jieba tokens -> stopword removal -> SQLite FTS5 OR query -> BM25 ranking.
- `llm_sparse_bm25`: original query -> LLM sparse terms -> SQLite FTS5 BM25.
- `dense`: original query -> embedding -> Chroma cosine search.
- `hybrid_rrf`: project hybrid retrieval, sparse BM25 + dense, fused by RRF.
- `multi_query_*`: same retrieval method run over `sample.queries` and fused by RRF; useful only when `queries` contains real query rewrites.

## Review Status

Recommended status meanings:

- `auto_accepted`: accepted by the model, not yet manually confirmed.
- `needs_human_review`: model revised or rejected the sample, or confidence is low.
- `reviewed`: manually accepted for evaluation.
- `rejected`: manually rejected and should not be used in final metrics.
- `needs_review`: draft or incomplete manual decision.

## Corpus Scope

The dataset file should not contain every negative candidate chunk. It should
contain questions and labels. The eval runner defaults to `--user-scope dataset`
and supports three corpus scopes:

- `sample`: search only `sample.user_id`; useful for product-style user isolation.
- `dataset`: search all user IDs present in the dataset; use this for the current 140/100-sample retrieval benchmark.
- `all`: search the full SQLite/Chroma corpus with no user filter; usually too broad for this benchmark.

For reproducible experiments, optionally add a separate corpus snapshot JSON
containing all chunks in scope, for example all chunks from the two users used
to generate the 140 samples.

Current useful companion files:

- `meeting_retrieval_eval.llm_draft_140.jsonl`: LLM-generated draft questions.
- `meeting_retrieval_eval.auto_reviewed_140.jsonl`: model-reviewed and repaired questions.
- `meeting_retrieval_eval.review_work.jsonl`: manual review working copy.
- `meeting_retrieval_eval.final.jsonl`: finalized samples exported from manual review.
- `meeting_retrieval_eval.final_100.jsonl`: optional 100-row set mixing `reviewed` and `auto_accepted`.
- `meeting_retrieval_eval.multi_evidence_draft_50.jsonl`: draft questions requiring multiple chunks.
- `meeting_retrieval_eval.multi_evidence_final_50.jsonl`: reviewed multi-evidence eval set.
- `meeting_retrieval_eval.llm_draft_140.meetings.json`: positive evidence meetings/chunks for inspection.
