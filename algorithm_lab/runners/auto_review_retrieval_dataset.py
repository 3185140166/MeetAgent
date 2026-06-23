# -*- coding: utf-8 -*-
"""Auto-review and repair LLM-generated retrieval evaluation samples.

The reviewer checks whether each question is directly answerable from its
labelled source chunk. Good samples are accepted. Weak samples are rewritten
against the same chunk when possible. Unsupported samples are rejected.

Usage:
    python -m algorithm_lab.runners.auto_review_retrieval_dataset \
      --input algorithm_lab/datasets/meeting_retrieval_eval.llm_draft_140.jsonl \
      --output algorithm_lab/datasets/meeting_retrieval_eval.auto_reviewed_140.jsonl \
      --review-model deepseek-v4-pro-max
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from app.config import APIFUSION_API_KEY, APIFUSION_API_URL, APIFUSION_MODEL


DEFAULT_OUTPUT = "algorithm_lab/datasets/meeting_retrieval_eval.auto_reviewed.jsonl"
VALID_STATUSES = {"accept", "revise", "reject"}


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


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def load_existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                print(f"Warning: ignoring invalid JSONL line {path}:{line_no}", file=sys.stderr)
                continue
            row_id = row.get("id")
            if row_id:
                ids.add(str(row_id))
    return ids


def extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip().rstrip("`").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


async def chat_json(
    *,
    messages: list[dict[str, str]],
    model: str,
    temperature: float,
    timeout: float,
) -> dict[str, Any]:
    if not APIFUSION_API_KEY:
        raise ValueError("APIFUSION_API_KEY is not set. Check your .env file.")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {APIFUSION_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(APIFUSION_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return extract_json(data["choices"][0]["message"]["content"])


def build_review_messages(row: dict[str, Any]) -> list[dict[str, str]]:
    source = row.get("source") or {}
    text = str(source.get("text_preview") or "")[:2200]
    keywords = row.get("relevant_keywords") or []
    difficulty = row.get("difficulty") or "medium"
    return [
        {
            "role": "system",
            "content": (
                "你是严格的会议检索评测集审核员。你的任务是判断一个用户问题是否可以由给定会议片段直接支持，"
                "并在必要时基于同一个片段重写问题和检索关键词。\n"
                "只输出 JSON，不要输出 markdown。\n"
                "判定标准：\n"
                "1. accept：原问题自然、完整，并且答案能由片段直接支持。\n"
                "2. revise：原问题相关但不够自然、太泛、表述错误、关键词差，或只需改写即可由片段直接支持。\n"
                "3. reject：片段不能回答该问题，或问题需要片段外信息，且无法基于片段改成有价值问题。\n"
                "如果 revise，必须给出 revised_question 和 revised_keywords。\n"
                "revised_question 必须像真实用户会问的问题，不要暴露 note_id/chunk_id，不要照抄整段原文。\n"
                "keywords 给 3 到 8 个适合 BM25 的中文实体、主题、术语或短语。\n"
                "输出格式："
                "{\"status\":\"accept|revise|reject\","
                "\"confidence\":0.0,"
                "\"reason\":\"简短原因\","
                "\"evidence_summary\":\"片段中可支持问题的依据摘要\","
                "\"revised_question\":\"\","
                "\"revised_keywords\":[\"关键词\"]}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"样本ID：{row.get('id')}\n"
                f"难度：{difficulty}\n"
                f"原问题：{row.get('question') or ''}\n"
                f"原关键词：{json.dumps(keywords, ensure_ascii=False)}\n"
                f"会议标题：{source.get('title') or ''}\n"
                f"会议时间：{source.get('create_time') or ''}\n"
                f"片段文本：\n{text}"
            ),
        },
    ]


def normalize_review(raw: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "").strip().lower()
    if status not in VALID_STATUSES:
        status = "reject"

    try:
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))

    revised_question = str(raw.get("revised_question") or "").strip()
    revised_keywords = [
        str(item).strip()
        for item in (raw.get("revised_keywords") or [])
        if str(item).strip()
    ][:8]

    if status == "revise" and (not revised_question or len(revised_keywords) < 2):
        status = "reject"

    return {
        "status": status,
        "confidence": confidence,
        "reason": str(raw.get("reason") or "").strip(),
        "evidence_summary": str(raw.get("evidence_summary") or "").strip(),
        "revised_question": revised_question,
        "revised_keywords": revised_keywords,
        "original_question": row.get("question") or "",
        "original_keywords": row.get("relevant_keywords") or [],
    }


def apply_review(row: dict[str, Any], review: dict[str, Any], model: str) -> dict[str, Any]:
    result = dict(row)
    result["auto_review"] = {
        "model": model,
        "status": review["status"],
        "confidence": review["confidence"],
        "reason": review["reason"],
        "evidence_summary": review["evidence_summary"],
        "original_question": review["original_question"],
        "original_keywords": review["original_keywords"],
    }

    if review["status"] == "accept":
        result["auto_review_status"] = "accepted"
        result["review_status"] = "auto_accepted"
        return result

    if review["status"] == "revise":
        result["auto_review_status"] = "revised"
        result["review_status"] = "needs_human_review"
        result["question"] = review["revised_question"]
        result["queries"] = [review["revised_question"]]
        result["relevant_keywords"] = review["revised_keywords"]
        result["auto_review"]["revised_question"] = review["revised_question"]
        result["auto_review"]["revised_keywords"] = review["revised_keywords"]
        return result

    result["auto_review_status"] = "rejected"
    result["review_status"] = "needs_human_review"
    return result


async def review_one(
    row: dict[str, Any],
    *,
    model: str,
    temperature: float,
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    messages = build_review_messages(row)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            raw = await chat_json(
                messages=messages,
                model=model,
                temperature=temperature,
                timeout=timeout,
            )
            review = normalize_review(raw, row)
            return apply_review(row, review, model)
        except Exception as exc:  # noqa: BLE001 - preserve row and error for manual review.
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(1.5 * (attempt + 1))

    result = dict(row)
    result["auto_review_status"] = "error"
    result["review_status"] = "needs_human_review"
    result["auto_review"] = {
        "model": model,
        "status": "error",
        "reason": str(last_error),
        "original_question": row.get("question") or "",
        "original_keywords": row.get("relevant_keywords") or [],
    }
    return result


async def run_auto_review(
    *,
    input_path: Path,
    output_path: Path,
    model: str,
    temperature: float,
    timeout: float,
    retries: int,
    resume: bool,
    limit: int | None,
) -> None:
    rows = read_jsonl(input_path)
    if limit is not None:
        rows = rows[:limit]

    existing_ids = load_existing_ids(output_path) if resume else set()
    if output_path.exists() and not resume:
        output_path.unlink()

    total = len(rows)
    done = 0
    counts: dict[str, int] = {}
    for index, row in enumerate(rows, 1):
        row_id = str(row["id"])
        if row_id in existing_ids:
            print(f"[{index}/{total}] skip {row_id}")
            continue
        reviewed = await review_one(
            row,
            model=model,
            temperature=temperature,
            timeout=timeout,
            retries=retries,
        )
        status = str(reviewed.get("auto_review_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        append_jsonl(output_path, reviewed)
        done += 1
        print(f"[{index}/{total}] {row_id} -> {status}")

    print(f"Wrote {done} new rows to {output_path}")
    print(json.dumps(counts, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-review LLM retrieval dataset JSONL")
    parser.add_argument("--input", required=True, help="Input retrieval JSONL")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output reviewed JSONL")
    parser.add_argument(
        "--review-model",
        default=os.environ.get("AUTO_REVIEW_MODEL") or APIFUSION_MODEL,
        help="Reviewer model. Defaults to AUTO_REVIEW_MODEL or APIFUSION_MODEL.",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="Only review first N rows")
    parser.add_argument("--no-resume", action="store_true", help="Overwrite output instead of skipping existing ids")
    args = parser.parse_args()

    asyncio.run(run_auto_review(
        input_path=Path(args.input),
        output_path=Path(args.output),
        model=args.review_model,
        temperature=args.temperature,
        timeout=args.timeout,
        retries=args.retries,
        resume=not args.no_resume,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
