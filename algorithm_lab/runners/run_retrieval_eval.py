# -*- coding: utf-8 -*-
"""Run offline retrieval evaluation against the local MeetAgent database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from algorithm_lab.baselines.retrieval import BASELINES
from algorithm_lab.metrics.retrieval_metrics import aggregate_metrics, evaluate_retrieval


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def _queries_for_sample(sample: dict) -> list[str]:
    queries = sample.get("queries")
    if isinstance(queries, list) and queries:
        return [str(query) for query in queries]
    return [str(sample.get("question") or "")]


def run_eval(dataset: list[dict], baseline: str, top_k: int) -> dict:
    baseline_fn = BASELINES[baseline]
    details: list[dict] = []
    metrics = []

    for sample in dataset:
        user_id = sample.get("user_id")
        if baseline.startswith("multi_query"):
            hits = baseline_fn(_queries_for_sample(sample), user_id=user_id, top_k=top_k)
        else:
            hits = baseline_fn(str(sample.get("question") or ""), user_id=user_id, top_k=top_k)

        item_metrics = evaluate_retrieval(hits, sample)
        metrics.append(item_metrics)
        details.append({
            "id": sample.get("id"),
            "question": sample.get("question"),
            "metrics": item_metrics.to_dict(),
            "top_hits": [
                {
                    "rank": index,
                    "chunk_id": hit.get("chunk_id"),
                    "note_id": hit.get("note_id"),
                    "title": hit.get("title"),
                    "create_time": hit.get("create_time"),
                    "score": hit.get("multi_rrf_score") or hit.get("rrf_score") or hit.get("score"),
                    "matched_queries": hit.get("matched_queries"),
                    "text_preview": str(hit.get("text") or "")[:160],
                }
                for index, hit in enumerate(hits, 1)
            ],
        })

    return {
        "baseline": baseline,
        "top_k": top_k,
        "summary": aggregate_metrics(metrics),
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MeetAgent retrieval baseline evaluation")
    parser.add_argument("--dataset", required=True, help="JSONL evaluation dataset")
    parser.add_argument("--baseline", choices=sorted(BASELINES), default="bm25")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--output", default="", help="Optional JSON report path")
    args = parser.parse_args()

    dataset = load_jsonl(Path(args.dataset))
    report = run_eval(dataset, baseline=args.baseline, top_k=args.top_k)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
