# -*- coding: utf-8 -*-
"""Build multi-evidence retrieval evaluation drafts.

This creates samples shaped like meeting_retrieval_eval.final_100.jsonl, but
each question is generated from multiple source chunks and every source chunk is
written to relevant_chunk_ids. The output is a draft and should be reviewed
before final evaluation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Any

from app.llm.client import chat
from app.storage.db import get_connection


DEFAULT_OUTPUT = "algorithm_lab/datasets/meeting_retrieval_eval.multi_evidence_draft_50.jsonl"


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


def load_candidate_windows(
    *,
    user_ids: list[str],
    window_size: int,
    min_chars: int,
) -> list[list[dict[str, Any]]]:
    conn = get_connection()
    windows: list[list[dict[str, Any]]] = []
    for user_id in user_ids:
        meetings = conn.execute(
            """
            SELECT note_id, title, create_time
            FROM meetings
            WHERE user_id = ?
            ORDER BY create_time DESC, note_id
            """,
            (user_id,),
        ).fetchall()
        for meeting in meetings:
            chunks = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                      c.chunk_id,
                      c.note_id,
                      c.user_id,
                      c.chunk_index,
                      c.speaker,
                      c.text,
                      m.title,
                      m.create_time
                    FROM chunks c
                    JOIN meetings m ON m.note_id = c.note_id
                    WHERE c.note_id = ? AND length(c.text) >= ?
                    ORDER BY c.chunk_index ASC
                    """,
                    (meeting["note_id"], min_chars),
                ).fetchall()
            ]
            if len(chunks) < window_size:
                continue
            for start in range(0, len(chunks) - window_size + 1):
                window = chunks[start : start + window_size]
                # Require adjacent chunks from the original meeting, not just
                # adjacent after min-length filtering.
                indexes = [int(chunk["chunk_index"]) for chunk in window]
                if indexes != list(range(indexes[0], indexes[0] + window_size)):
                    continue
                windows.append(window)
    conn.close()
    return windows


def format_context(chunks: list[dict[str, Any]], max_chars_per_chunk: int) -> str:
    parts = []
    for index, chunk in enumerate(chunks, 1):
        text = str(chunk.get("text") or "")[:max_chars_per_chunk]
        parts.append(
            "\n".join([
                f"[chunk_{index}]",
                f"chunk_id: {chunk.get('chunk_id')}",
                f"title: {chunk.get('title') or ''}",
                f"create_time: {chunk.get('create_time') or ''}",
                f"chunk_index: {chunk.get('chunk_index')}",
                f"text: {text}",
            ])
        )
    return "\n\n".join(parts)


async def generate_multi_evidence_question(
    *,
    chunks: list[dict[str, Any]],
    max_chars_per_chunk: int,
    temperature: float,
) -> dict[str, Any]:
    context = format_context(chunks, max_chars_per_chunk)
    messages = [
        {
            "role": "system",
            "content": (
                "你是会议检索评测集构造助手。请根据给定的多个会议 chunks，生成一个真实用户可能提出的检索问题。"
                "这个问题必须需要结合至少两个 chunks 才能完整回答，不能只靠其中一个 chunk 回答。"
                "只输出 JSON，不要输出 markdown。输出格式："
                "{\"question\":\"问题\",\"queries\":[\"检索 query\"],\"keywords\":[\"关键词\"],"
                "\"evidence_requirements\":[{\"chunk_id\":\"...\",\"required_fact\":\"这个 chunk 提供的必要信息\"}]}"
                "要求：question 自然、具体；queries 放 1 到 3 个可用于检索的自然 query；"
                "keywords 放 4 到 10 个适合稀疏检索的中文实体、主题、术语或短语；"
                "evidence_requirements 必须覆盖至少两个不同 chunk_id。"
            ),
        },
        {
            "role": "user",
            "content": f"请基于这些 chunks 生成 1 条多证据检索问题：\n\n{context}",
        },
    ]
    raw = await chat(messages, temperature=temperature)
    parsed = extract_json(raw)

    question = str(parsed.get("question") or "").strip()
    queries = [
        str(item).strip()
        for item in parsed.get("queries") or []
        if str(item).strip()
    ][:3]
    keywords = [
        str(item).strip()
        for item in parsed.get("keywords") or []
        if str(item).strip()
    ][:10]
    requirements = [
        item
        for item in parsed.get("evidence_requirements") or []
        if isinstance(item, dict) and str(item.get("chunk_id") or "").strip()
    ]

    if not question:
        raise ValueError("LLM returned empty question")
    if len({str(item.get("chunk_id")) for item in requirements}) < 2:
        raise ValueError("LLM did not provide evidence requirements for at least two chunks")

    return {
        "question": question,
        "queries": queries or [question],
        "keywords": keywords,
        "evidence_requirements": requirements,
    }


async def build_dataset_async(
    *,
    user_ids: list[str],
    output: Path,
    target_count: int,
    window_size: int,
    min_chars: int,
    max_chars_per_chunk: int,
    seed: int,
    temperature: float,
    resume: bool,
) -> None:
    windows = load_candidate_windows(
        user_ids=user_ids,
        window_size=window_size,
        min_chars=min_chars,
    )
    rng = random.Random(seed)
    rng.shuffle(windows)
    existing_ids = load_existing_ids(output) if resume else set()
    written = 0
    attempts = 0

    print(
        f"Multi-evidence plan: candidates={len(windows)}, target={target_count}, "
        f"window_size={window_size}, existing={len(existing_ids)}"
    )

    for window in windows:
        if written >= target_count:
            break
        attempts += 1
        row_index = len(existing_ids) + written + 1
        row_id = f"multi_evidence_{row_index:04d}"
        if row_id in existing_ids:
            continue
        chunk_ids = [str(chunk["chunk_id"]) for chunk in window]
        print(f"[{written + 1}/{target_count}] generating {row_id}: {chunk_ids}")
        try:
            generated = await generate_multi_evidence_question(
                chunks=window,
                max_chars_per_chunk=max_chars_per_chunk,
                temperature=temperature,
            )
        except Exception as exc:
            print(f"  skip: {type(exc).__name__}: {exc}")
            continue

        note_ids = sorted({str(chunk["note_id"]) for chunk in window})
        row = {
            "id": row_id,
            "user_id": str(window[0]["user_id"]),
            "question": generated["question"],
            "queries": generated["queries"],
            "relevant_note_ids": note_ids,
            "relevant_chunk_ids": chunk_ids,
            "relevant_keywords": generated["keywords"],
            "label_type": "llm_multi_evidence_question",
            "difficulty": "multi_evidence",
            "review_status": "needs_review",
            "review_hint": (
                "Check that at least two source chunks are necessary. Reject or rewrite if one chunk alone "
                "can answer the question."
            ),
            "source": {
                "note_id": str(window[0]["note_id"]),
                "chunk_id": chunk_ids[0],
                "title": window[0].get("title"),
                "create_time": window[0].get("create_time"),
                "chunk_index": window[0].get("chunk_index"),
                "text_preview": "\n\n".join(
                    f"[{chunk['chunk_id']}]\n{str(chunk.get('text') or '')[:700]}"
                    for chunk in window
                ),
                "chunks": [
                    {
                        "note_id": chunk.get("note_id"),
                        "chunk_id": chunk.get("chunk_id"),
                        "title": chunk.get("title"),
                        "create_time": chunk.get("create_time"),
                        "chunk_index": chunk.get("chunk_index"),
                        "text_preview": str(chunk.get("text") or "")[:700],
                    }
                    for chunk in window
                ],
                "evidence_requirements": generated["evidence_requirements"],
            },
        }
        append_jsonl(output, row)
        written += 1
        existing_ids.add(row_id)

    print(json.dumps({
        "output": str(output),
        "written": written,
        "attempts": attempts,
        "target_count": target_count,
        "candidate_windows": len(windows),
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build multi-evidence retrieval dataset drafts")
    parser.add_argument("--user-id", action="append", required=True, help="User ID; repeat for multiple users")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--target-count", type=int, default=50)
    parser.add_argument("--window-size", type=int, default=3, help="Adjacent chunks per sample")
    parser.add_argument("--min-chars", type=int, default=250, help="Minimum chars per source chunk")
    parser.add_argument("--max-chars-per-chunk", type=int, default=900)
    parser.add_argument("--seed", type=int, default=777)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    if args.window_size < 2:
        raise SystemExit("--window-size must be at least 2")

    asyncio.run(build_dataset_async(
        user_ids=args.user_id,
        output=Path(args.output),
        target_count=args.target_count,
        window_size=args.window_size,
        min_chars=args.min_chars,
        max_chars_per_chunk=args.max_chars_per_chunk,
        seed=args.seed,
        temperature=args.temperature,
        resume=not args.no_resume,
    ))


if __name__ == "__main__":
    main()
