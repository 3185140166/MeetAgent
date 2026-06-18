# -*- coding: utf-8 -*-
"""Export reviewed training datasets from agent_eval_samples."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import VALID_EXPORT_TYPES, dump_jsonl, iter_samples


def to_tool_call_record(sample: dict) -> dict | None:
    tool_trace = sample.get("tool_trace") or []
    if not tool_trace:
        return None
    return {
        "sample_id": sample["sample_id"],
        "type": "tool_call",
        "messages": [
            {
                "role": "user",
                "content": sample["question"],
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "name": item.get("tool"),
                        "arguments": item.get("arguments") or {},
                    }
                    for item in tool_trace
                ],
            },
        ],
        "quality_score": sample["quality_score"],
    }


def to_answer_record(sample: dict) -> dict | None:
    answer = (sample.get("final_answer") or "").strip()
    if not answer:
        return None
    return {
        "sample_id": sample["sample_id"],
        "type": "answer_generation",
        "input": {
            "question": sample["question"],
            "tool_results": sample.get("tool_results") or [],
            "sources": sample.get("sources") or [],
        },
        "output": answer,
        "quality_score": sample["quality_score"],
    }


def to_preference_record(sample: dict) -> dict | None:
    draft = (sample.get("draft_answer") or "").strip()
    final = (sample.get("final_answer") or "").strip()
    if not draft or not final or draft == final:
        return None
    return {
        "sample_id": sample["sample_id"],
        "type": "preference",
        "prompt": {
            "question": sample["question"],
            "sources": sample.get("sources") or [],
        },
        "chosen": final,
        "rejected": draft,
        "verification": sample.get("verification") or {},
        "quality_score": sample["quality_score"],
    }


CONVERTERS = {
    "tool_call": to_tool_call_record,
    "answer_generation": to_answer_record,
    "preference": to_preference_record,
}


def export(args) -> int:
    samples = iter_samples(
        db_path=args.db,
        sample_type=None if args.type == "all" else args.type,
        review_status=args.review_status,
        user_id=args.user_id,
        min_score=args.min_score,
        passed_only=args.passed_only,
        no_failed_tools=args.no_failed_tools,
        require_sources=args.require_sources,
        limit=args.limit,
    )

    export_types = list(CONVERTERS) if args.type == "all" else [args.type]
    records = []
    for sample in samples:
        for export_type in export_types:
            record = CONVERTERS[export_type](sample)
            if record:
                records.append(record)

    return dump_jsonl(args.output, records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export reviewed training JSONL datasets")
    parser.add_argument("--db", default="data/meetagent.db")
    parser.add_argument("--type", choices=sorted(VALID_EXPORT_TYPES), default="all")
    parser.add_argument("--output", default="data/training/agent_training_data.jsonl")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--review-status", default="accepted")
    parser.add_argument("--min-score", type=float, default=70)
    parser.add_argument("--passed-only", action="store_true")
    parser.add_argument("--no-failed-tools", action="store_true", default=True)
    parser.add_argument("--allow-failed-tools", dest="no_failed_tools", action="store_false")
    parser.add_argument("--require-sources", action="store_true")
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    count = export(args)
    print(f"exported {count} records to {Path(args.output)}")


if __name__ == "__main__":
    main()
