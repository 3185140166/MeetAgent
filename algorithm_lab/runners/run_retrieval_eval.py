# -*- coding: utf-8 -*-
"""Run offline retrieval evaluation against the local MeetAgent database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from algorithm_lab.baselines.retrieval import BASELINES
from algorithm_lab.metrics.retrieval_metrics import aggregate_metrics, evaluate_retrieval

UserFilter = str | list[str] | None


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


def _dataset_user_ids(dataset: list[dict]) -> list[str]:
    return sorted({
        str(sample.get("user_id")).strip()
        for sample in dataset
        if str(sample.get("user_id") or "").strip()
    })


def _user_filter_for_sample(sample: dict, user_scope: str, dataset_user_ids: list[str]) -> UserFilter:
    if user_scope == "sample":
        return str(sample.get("user_id") or "").strip() or None
    if user_scope == "dataset":
        return dataset_user_ids or None
    if user_scope == "all":
        return None
    raise ValueError(f"unknown user_scope: {user_scope}")


def run_eval(dataset: list[dict], baseline: str, top_k: int, user_scope: str = "dataset") -> dict:
    baseline_fn = BASELINES[baseline]
    details: list[dict] = []
    metrics = []
    dataset_user_ids = _dataset_user_ids(dataset)

    for sample in dataset:
        user_filter = _user_filter_for_sample(sample, user_scope, dataset_user_ids)
        if baseline.startswith("multi_query"):
            hits = baseline_fn(_queries_for_sample(sample), user_id=user_filter, top_k=top_k)
        else:
            hits = baseline_fn(str(sample.get("question") or ""), user_id=user_filter, top_k=top_k)

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
            "user_filter": user_filter,
        })

    return {
        "baseline": baseline,
        "top_k": top_k,
        "user_scope": user_scope,
        "dataset_user_ids": dataset_user_ids,
        "summary": aggregate_metrics(metrics),
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MeetAgent retrieval baseline evaluation")
    parser.add_argument("--dataset", required=True, help="JSONL evaluation dataset")
    parser.add_argument("--baseline", choices=sorted(BASELINES), default="bm25")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument(
        "--user-scope",
        choices=["sample", "dataset", "all"],
        default="dataset",
        help=(
            "Candidate chunk scope: sample=only sample.user_id; "
            "dataset=all user_ids present in the dataset; all=no user filter."
        ),
    )
    parser.add_argument("--output", default="", help="Optional JSON report path")
    args = parser.parse_args()

    dataset = load_jsonl(Path(args.dataset))
    report = run_eval(dataset, baseline=args.baseline, top_k=args.top_k, user_scope=args.user_scope)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
