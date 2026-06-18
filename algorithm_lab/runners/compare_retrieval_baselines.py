# -*- coding: utf-8 -*-
"""Compare multiple retrieval baselines on the same dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from algorithm_lab.baselines.retrieval import BASELINES
from algorithm_lab.runners.run_retrieval_eval import load_jsonl, run_eval


def _format_float(value: float) -> str:
    return f"{value:.4f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare MeetAgent retrieval baselines")
    parser.add_argument("--dataset", required=True, help="JSONL evaluation dataset")
    parser.add_argument(
        "--baselines",
        nargs="+",
        default=["bm25", "multi_query_bm25"],
        choices=sorted(BASELINES),
    )
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--output", default="", help="Optional JSON report path")
    args = parser.parse_args()

    dataset = load_jsonl(Path(args.dataset))
    reports = [run_eval(dataset, baseline=baseline, top_k=args.top_k) for baseline in args.baselines]

    rows = []
    for report in reports:
        summary = report["summary"]
        rows.append({
            "baseline": report["baseline"],
            "sample_count": summary["sample_count"],
            "hit_rate": summary["hit_rate"],
            "recall": summary["recall"],
            "mrr": summary["mrr"],
            "keyword_hit_rate": summary["keyword_hit_rate"],
            "avg_result_count": summary["avg_result_count"],
        })

    print("| baseline | samples | hit_rate | recall | mrr | keyword_hit_rate | avg_results |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        print(
            f"| {row['baseline']} | {row['sample_count']} | "
            f"{_format_float(row['hit_rate'])} | {_format_float(row['recall'])} | "
            f"{_format_float(row['mrr'])} | {_format_float(row['keyword_hit_rate'])} | "
            f"{_format_float(row['avg_result_count'])} |"
        )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"top_k": args.top_k, "rows": rows, "reports": reports}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
