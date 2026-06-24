# -*- coding: utf-8 -*-
"""Export finalized retrieval eval samples from a reviewed JSONL file.

By default this keeps only manually accepted samples:

    review_status == "reviewed"

Use --include-auto-accepted when you intentionally want to include samples that
were accepted by the model but not manually confirmed.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = "algorithm_lab/datasets/meeting_retrieval_eval.final.jsonl"
DIFFICULTIES = ("easy", "medium", "hard")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            if not row.get("id"):
                raise ValueError(f"Missing id at {path}:{line_no}")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_for_eval(row: dict[str, Any], *, drop_review_metadata: bool) -> dict[str, Any]:
    result = dict(row)
    if drop_review_metadata:
        for key in (
            "auto_review",
            "auto_review_status",
            "review_hint",
            "reviewer_notes",
        ):
            result.pop(key, None)
    return result


def parse_difficulty_plan(value: str) -> dict[str, int]:
    if not value:
        return {}
    plan: dict[str, int] = {}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, count_text = item.partition(":")
        name = name.strip().lower()
        if name not in DIFFICULTIES or not count_text.strip().isdigit():
            raise ValueError("difficulty plan must look like easy:30,medium:50,hard:20")
        plan[name] = int(count_text.strip())
    return plan


def default_difficulty_plan(limit: int | None) -> dict[str, int]:
    if not limit:
        return {}
    easy = round(limit * 0.30)
    medium = round(limit * 0.50)
    hard = limit - easy - medium
    return {"easy": easy, "medium": medium, "hard": hard}


def row_priority(row: dict[str, Any]) -> int:
    status = str(row.get("review_status") or "")
    if status == "reviewed":
        return 0
    if status == "auto_accepted":
        return 1
    return 2


def stable_row_key(row: dict[str, Any]) -> str:
    return str(row.get("id") or "")


def select_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int | None,
    difficulty_plan: dict[str, int],
    seed: int,
) -> list[dict[str, Any]]:
    if not limit:
        return sorted(rows, key=lambda row: (row_priority(row), stable_row_key(row)))

    rng = random.Random(seed)
    plan = difficulty_plan or default_difficulty_plan(limit)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    by_difficulty: dict[str, list[dict[str, Any]]] = {name: [] for name in DIFFICULTIES}
    other: list[dict[str, Any]] = []
    for row in rows:
        difficulty = str(row.get("difficulty") or "").lower()
        if difficulty in by_difficulty:
            by_difficulty[difficulty].append(row)
        else:
            other.append(row)

    for bucket in [*by_difficulty.values(), other]:
        bucket.sort(key=lambda row: (row_priority(row), stable_row_key(row)))
        reviewed = [row for row in bucket if row_priority(row) == 0]
        auto = [row for row in bucket if row_priority(row) != 0]
        rng.shuffle(auto)
        bucket[:] = reviewed + auto

    for difficulty in DIFFICULTIES:
        target = plan.get(difficulty, 0)
        for row in by_difficulty[difficulty][:target]:
            row_id = stable_row_key(row)
            if row_id not in selected_ids:
                selected.append(row)
                selected_ids.add(row_id)

    if len(selected) < limit:
        remaining = [
            row
            for row in rows
            if stable_row_key(row) not in selected_ids
        ]
        remaining.sort(key=lambda row: (row_priority(row), stable_row_key(row)))
        reviewed = [row for row in remaining if row_priority(row) == 0]
        auto = [row for row in remaining if row_priority(row) != 0]
        rng.shuffle(auto)
        for row in reviewed + auto:
            if len(selected) >= limit:
                break
            selected.append(row)
            selected_ids.add(stable_row_key(row))

    selected = selected[:limit]
    selected.sort(key=lambda row: (row_priority(row), str(row.get("difficulty") or ""), stable_row_key(row)))
    return selected


def export_reviewed(
    *,
    input_path: Path,
    output_path: Path,
    include_auto_accepted: bool,
    drop_review_metadata: bool,
    limit: int | None,
    difficulty_plan: dict[str, int],
    seed: int,
) -> dict[str, Any]:
    rows = read_jsonl(input_path)
    accepted_statuses = {"reviewed"}
    if include_auto_accepted:
        accepted_statuses.add("auto_accepted")

    candidates = [
        row
        for row in rows
        if str(row.get("review_status") or "") in accepted_statuses
    ]
    selected_source_rows = select_rows(
        candidates,
        limit=limit,
        difficulty_plan=difficulty_plan,
        seed=seed,
    )
    selected = [
        normalize_for_eval(row, drop_review_metadata=drop_review_metadata)
        for row in selected_source_rows
    ]
    write_jsonl(output_path, selected)

    return {
        "input": str(input_path),
        "output": str(output_path),
        "input_rows": len(rows),
        "candidate_rows": len(candidates),
        "output_rows": len(selected),
        "review_status_counts": dict(Counter(str(row.get("review_status") or "") for row in rows)),
        "auto_review_status_counts": dict(Counter(str(row.get("auto_review_status") or "") for row in rows)),
        "output_review_status_counts": dict(Counter(str(row.get("review_status") or "") for row in selected_source_rows)),
        "output_difficulty_counts": dict(Counter(str(row.get("difficulty") or "") for row in selected_source_rows)),
        "included_statuses": sorted(accepted_statuses),
        "limit": limit,
        "difficulty_plan": difficulty_plan,
        "seed": seed,
        "drop_review_metadata": drop_review_metadata,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export finalized retrieval dataset from reviewed JSONL")
    parser.add_argument("--input", required=True, help="Reviewed JSONL, usually meeting_retrieval_eval.review_work.jsonl")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Final eval JSONL path")
    parser.add_argument(
        "--include-auto-accepted",
        action="store_true",
        help="Also include model-accepted samples that were not manually marked reviewed.",
    )
    parser.add_argument(
        "--keep-review-metadata",
        action="store_true",
        help="Keep auto_review/reviewer metadata in the exported eval file.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum exported rows, e.g. 100")
    parser.add_argument(
        "--difficulty-plan",
        default="",
        help="Target counts such as easy:30,medium:50,hard:20. Defaults to 30/50/20 split when --limit is set.",
    )
    parser.add_argument("--seed", type=int, default=666, help="Seed for sampling auto_accepted rows")
    args = parser.parse_args()

    summary = export_reviewed(
        input_path=Path(args.input),
        output_path=Path(args.output),
        include_auto_accepted=args.include_auto_accepted,
        drop_review_metadata=not args.keep_review_metadata,
        limit=args.limit,
        difficulty_plan=parse_difficulty_plan(args.difficulty_plan),
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
