# -*- coding: utf-8 -*-
"""Export Agent eval samples as JSONL training candidates."""

import argparse
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.agent.eval_samples import (
    SAMPLE_ANSWER_GENERATION,
    SAMPLE_PREFERENCE,
    SAMPLE_TOOL_CALL,
    list_eval_samples,
    to_training_record,
)
from app.storage.db import init_db


EXPORT_TYPES = {
    SAMPLE_TOOL_CALL,
    SAMPLE_ANSWER_GENERATION,
    SAMPLE_PREFERENCE,
}


def export_jsonl(args) -> int:
    rows = list_eval_samples(
        sample_type=None if args.type == "all" else args.type,
        review_status=args.review_status,
        user_id=args.user_id,
        min_score=args.min_score,
        passed_only=args.passed_only,
        limit=args.limit,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            export_types = EXPORT_TYPES if args.type == "all" else {args.type}
            for export_type in export_types:
                record = to_training_record(row, export_type)
                if not record:
                    continue
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
    return written


def print_summary(args) -> None:
    rows = list_eval_samples(
        sample_type=None if args.type == "all" else args.type,
        review_status=args.review_status,
        user_id=args.user_id,
        min_score=args.min_score,
        passed_only=args.passed_only,
        limit=args.limit,
    )
    counts = {}
    for row in rows:
        counts[row["sample_type"]] = counts.get(row["sample_type"], 0) + 1
    print(f"候选样本: {len(rows)}")
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")
    if rows:
        print("\nTop samples:")
        for row in rows[: min(len(rows), 10)]:
            print(
                f"  {row['sample_id']}  type={row['sample_type']} "
                f"score={row['quality_score']} passed={row['passed']} "
                f"review={row['review_status']}  q={row['question'][:50]}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出 Agent 训练候选数据")
    parser.add_argument(
        "--type",
        choices=["all", SAMPLE_TOOL_CALL, SAMPLE_ANSWER_GENERATION, SAMPLE_PREFERENCE],
        default="all",
        help="导出类型",
    )
    parser.add_argument("--output", default="data/agent_training_data.jsonl", help="输出 JSONL 文件")
    parser.add_argument("--user-id", default=None, help="只导出指定用户")
    parser.add_argument("--review-status", default=None, help="pending / accepted / rejected / fixed")
    parser.add_argument("--min-score", type=float, default=70, help="最低质量分")
    parser.add_argument("--passed-only", action="store_true", help="只导出 verifier 通过的样本")
    parser.add_argument("--limit", type=int, default=1000, help="最多读取样本数")
    parser.add_argument("--summary", action="store_true", help="只显示统计，不写文件")
    args = parser.parse_args()

    init_db()

    if args.summary:
        print_summary(args)
    else:
        count = export_jsonl(args)
        print(f"已导出 {count} 条训练候选记录到 {args.output}")
