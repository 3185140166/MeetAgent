# -*- coding: utf-8 -*-
"""Inspect and review agent evaluation samples."""

from __future__ import annotations

import argparse
import json
from collections import Counter

from common import (
    VALID_REVIEW_STATUSES,
    connect,
    iter_samples,
    update_review_status,
)


def cmd_summary(args) -> None:
    samples = iter_samples(
        db_path=args.db,
        sample_type=args.type,
        review_status=args.review_status,
        user_id=args.user_id,
        min_score=args.min_score,
        passed_only=args.passed_only,
        limit=args.limit,
    )
    by_type = Counter(sample["sample_type"] for sample in samples)
    by_review = Counter(sample["review_status"] for sample in samples)
    by_passed = Counter("passed" if sample["passed"] else "failed" for sample in samples)
    print(f"samples: {len(samples)}")
    print("by_type:", dict(by_type))
    print("by_review:", dict(by_review))
    print("by_passed:", dict(by_passed))


def cmd_list(args) -> None:
    samples = iter_samples(
        db_path=args.db,
        sample_type=args.type,
        review_status=args.review_status,
        user_id=args.user_id,
        min_score=args.min_score,
        passed_only=args.passed_only,
        no_failed_tools=args.no_failed_tools,
        require_sources=args.require_sources,
        limit=args.limit,
    )
    for sample in samples:
        question = (sample["question"] or "").replace("\n", " ")[:90]
        print(
            f"{sample['sample_id']}  type={sample['sample_type']} "
            f"score={sample['quality_score']} passed={sample['passed']} "
            f"review={sample['review_status']}  q={question}"
        )


def cmd_show(args) -> None:
    conn = connect(args.db)
    try:
        row = conn.execute(
            "SELECT * FROM agent_eval_samples WHERE sample_id = ?",
            (args.sample_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise SystemExit(f"sample not found: {args.sample_id}")
    sample = dict(row)
    for key in ("tool_trace", "tool_results", "sources", "verification"):
        try:
            sample[key] = json.loads(sample[key]) if sample.get(key) else None
        except Exception:
            pass
    print(json.dumps(sample, ensure_ascii=False, indent=2))


def cmd_mark(args) -> None:
    ok = update_review_status(args.sample_id, args.status, db_path=args.db)
    if not ok:
        raise SystemExit(f"sample not found: {args.sample_id}")
    print(f"marked {args.sample_id} as {args.status}")


def add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default="data/meetagent.db")
    parser.add_argument("--type", default=None, choices=[None, "tool_call", "answer_generation", "preference", "all"])
    parser.add_argument("--review-status", default=None)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--min-score", type=float, default=0)
    parser.add_argument("--passed-only", action="store_true")
    parser.add_argument("--no-failed-tools", action="store_true")
    parser.add_argument("--require-sources", action="store_true")
    parser.add_argument("--limit", type=int, default=50)


def main() -> None:
    parser = argparse.ArgumentParser(description="Review agent eval samples")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("summary")
    add_filters(p)
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("list")
    add_filters(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show")
    p.add_argument("sample_id")
    p.add_argument("--db", default="data/meetagent.db")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("mark")
    p.add_argument("sample_id")
    p.add_argument("--status", required=True, choices=sorted(VALID_REVIEW_STATUSES))
    p.add_argument("--db", default="data/meetagent.db")
    p.set_defaults(func=cmd_mark)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
