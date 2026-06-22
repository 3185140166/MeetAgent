# -*- coding: utf-8 -*-
"""Build retrieval evaluation datasets or annotation candidates.

This script reads the existing MeetAgent SQLite corpus. It does not import raw
meeting JSON files and does not write to the application database.

Modes:
  weak      Build a weakly labelled JSONL dataset by sampling chunks and using
            extracted keywords as queries. The sampled chunk/note is treated as
            the positive evidence.
  llm       Sample chunks and ask the configured LLM to generate natural user
            questions. The source chunk is prefilled as positive evidence, but
            rows are marked as needs_review. Use --difficulty-plan to generate
            a balanced easy/medium/hard draft set.
  annotate  Read human-written queries and output retrieval candidates for
            manual positive-label annotation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import Iterable

import jieba.analyse

from app.search.bm25 import search as bm25_search
from app.storage.db import get_connection


DEFAULT_OUTPUT = "algorithm_lab/datasets/meeting_retrieval_eval.generated.jsonl"
EXTRA_STOPWORDS = {
    "我们",
    "你们",
    "他们",
    "就是",
    "然后",
    "这个",
    "那个",
    "什么",
    "一个",
    "不是",
    "是不是",
    "的话",
    "其实",
    "大家",
    "所以",
    "因为",
    "可以",
}


def _load_stopwords() -> set[str]:
    stopwords = set(EXTRA_STOPWORDS)
    path = Path("data/stopwords.txt")
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            stopwords.update(line.strip() for line in f if line.strip())
    return stopwords


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


def _load_existing_ids(path: Path) -> set[str]:
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


def _load_query_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith("{"):
                row = json.loads(line)
            else:
                parts = line.split("\t")
                row = {"question": parts[0]}
                if len(parts) > 1 and parts[1]:
                    row["user_id"] = parts[1]
            if not row.get("question") and not row.get("query"):
                raise ValueError(f"Missing question/query at {path}:{line_no}")
            rows.append(row)
    return rows


def _sample_chunks(user_ids: list[str], per_user: int, min_chars: int, seed: int) -> list[dict]:
    random.seed(seed)
    conn = get_connection()
    samples: list[dict] = []
    for user_id in user_ids:
        rows = [
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
                WHERE c.user_id = ? AND length(c.text) >= ?
                ORDER BY m.create_time DESC, c.chunk_index ASC
                """,
                (user_id, min_chars),
            ).fetchall()
        ]
        if len(rows) <= per_user:
            samples.extend(rows)
        else:
            samples.extend(random.sample(rows, per_user))
    conn.close()
    samples.sort(key=lambda row: (row["user_id"], row["create_time"], row["chunk_index"]))
    return samples


def _load_chunks_by_user(user_ids: list[str], min_chars: int, seed: int) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    conn = get_connection()
    result: dict[str, list[dict]] = {}
    for user_id in user_ids:
        rows = [
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
                WHERE c.user_id = ? AND length(c.text) >= ?
                ORDER BY m.create_time DESC, c.chunk_index ASC
                """,
                (user_id, min_chars),
            ).fetchall()
        ]
        rng.shuffle(rows)
        result[user_id] = rows
    conn.close()
    return result


def _parse_difficulty_plan(value: str) -> dict[str, int]:
    if not value:
        return {}
    plan: dict[str, int] = {}
    valid = {"easy", "medium", "hard"}
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, count_text = item.partition(":")
        name = name.strip().lower()
        if name not in valid or not count_text.strip().isdigit():
            raise ValueError("difficulty plan must look like easy:30,medium:50,hard:20")
        plan[name] = int(count_text.strip())
    return plan


def _take_balanced_chunks(
    *,
    user_ids: list[str],
    min_chars: int,
    seed: int,
    difficulty_plan: dict[str, int],
) -> list[tuple[str, dict]]:
    chunks_by_user = _load_chunks_by_user(user_ids, min_chars, seed)
    offsets = {user_id: 0 for user_id in user_ids}
    selected: list[tuple[str, dict]] = []

    for difficulty, total in difficulty_plan.items():
        for index in range(total):
            user_id = user_ids[index % len(user_ids)]
            chunks = chunks_by_user.get(user_id) or []
            offset = offsets[user_id]
            if offset >= len(chunks):
                raise ValueError(f"Not enough chunks for user_id={user_id}")
            selected.append((difficulty, chunks[offset]))
            offsets[user_id] = offset + 1
    return selected


def _keywords(text: str, top_k: int) -> list[str]:
    stopwords = _load_stopwords()
    tags = jieba.analyse.extract_tags(text, topK=max(top_k * 2, 8))
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        tag = str(tag).strip()
        if len(tag) < 2 or tag in seen or tag in stopwords:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= top_k:
            break
    return result


def build_weak_dataset(
    *,
    user_ids: list[str],
    per_user: int,
    min_chars: int,
    keyword_count: int,
    seed: int,
) -> list[dict]:
    rows = []
    for index, chunk in enumerate(_sample_chunks(user_ids, per_user, min_chars, seed), 1):
        keywords = _keywords(chunk["text"], keyword_count)
        if not keywords:
            continue
        query = " ".join(keywords)
        rows.append({
            "id": f"weak_{index:04d}",
            "user_id": chunk["user_id"],
            "question": query,
            "natural_question": f"查找与{'、'.join(keywords[:3])}相关的会议内容",
            "queries": [query],
            "relevant_note_ids": [chunk["note_id"]],
            "relevant_chunk_ids": [chunk["chunk_id"]],
            "relevant_keywords": keywords,
            "label_type": "weak_chunk_keyword",
            "source": {
                "note_id": chunk["note_id"],
                "chunk_id": chunk["chunk_id"],
                "title": chunk.get("title"),
                "create_time": chunk.get("create_time"),
                "chunk_index": chunk.get("chunk_index"),
                "text_preview": chunk.get("text", "")[:220],
            },
        })
    return rows


def _parse_llm_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


async def _generate_queries_for_chunk(chunk: dict, query_count: int, difficulty: str) -> dict:
    from app.llm.client import chat

    text = str(chunk.get("text") or "")[:1800]
    difficulty_instruction = {
        "easy": (
            "生成 easy 问题：query 中应包含片段里的关键实体、术语或短语，"
            "与原文关键词高度一致，用于验证基础关键词检索。"
        ),
        "medium": (
            "生成 medium 问题：使用自然语言改写，不要完全照抄原文关键词，"
            "但问题仍应能被该片段直接支持。"
        ),
        "hard": (
            "生成 hard 问题：使用更抽象的表达、同义改写或容易混淆的问法，"
            "但不能超出片段证据范围。"
        ),
    }.get(difficulty, "生成自然、真实的用户检索问题。")
    messages = [
        {
            "role": "system",
            "content": (
                "你是会议检索评测集构造助手。请根据给定会议片段，生成真实用户可能会问的检索问题。\n"
                "只输出 JSON，不要 markdown。格式："
                "{\"questions\":[\"问题1\"],\"keywords\":[\"关键词1\"]}。\n"
                "要求：问题必须能由该片段直接支持；不要问片段外的信息；问题要自然，不要照抄整句；"
                "keywords 放适合 BM25 的实体、主题、术语或短语。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请生成 {query_count} 个检索问题。\n"
                f"难度：{difficulty}\n"
                f"难度要求：{difficulty_instruction}\n"
                f"会议标题：{chunk.get('title') or ''}\n"
                f"会议时间：{chunk.get('create_time') or ''}\n"
                f"片段：\n{text}"
            ),
        },
    ]
    raw = await chat(messages, temperature=0.2)
    parsed = _parse_llm_json(raw)
    questions = [
        str(item).strip()
        for item in parsed.get("questions") or []
        if str(item).strip()
    ][:query_count]
    keywords = [
        str(item).strip()
        for item in parsed.get("keywords") or []
        if str(item).strip()
    ][:8]
    return {"questions": questions, "keywords": keywords}


async def build_llm_dataset_async(
    *,
    user_ids: list[str],
    per_user: int,
    min_chars: int,
    seed: int,
    queries_per_chunk: int,
    difficulty_plan: dict[str, int] | None = None,
    output: Path | None = None,
    resume: bool = True,
) -> list[dict]:
    rows = []
    if difficulty_plan:
        selected_chunks = _take_balanced_chunks(
            user_ids=user_ids,
            min_chars=min_chars,
            seed=seed,
            difficulty_plan=difficulty_plan,
        )
    else:
        selected_chunks = [("medium", chunk) for chunk in _sample_chunks(user_ids, per_user, min_chars, seed)]

    existing_ids = _load_existing_ids(output) if output and resume else set()
    total_chunks = len(selected_chunks)
    total_expected = total_chunks * queries_per_chunk
    print(
        f"LLM generation plan: chunks={total_chunks}, queries_per_chunk={queries_per_chunk}, "
        f"expected_rows={total_expected}, existing_rows={len(existing_ids)}"
    )

    for chunk_index, (difficulty, chunk) in enumerate(selected_chunks, 1):
        id_prefix = f"llm_{difficulty}_{chunk_index:04d}"
        expected_ids = {f"{id_prefix}_{i:02d}" for i in range(1, queries_per_chunk + 1)}
        if expected_ids and expected_ids.issubset(existing_ids):
            print(f"[{chunk_index}/{total_chunks}] skip {difficulty} {chunk['chunk_id']} (already generated)")
            continue

        print(f"[{chunk_index}/{total_chunks}] generating {difficulty} {chunk['chunk_id']}...")
        generated = await _generate_queries_for_chunk(chunk, queries_per_chunk, difficulty)
        questions = generated.get("questions") or []
        keywords = generated.get("keywords") or []
        if not questions:
            print(f"[{chunk_index}/{total_chunks}] warning: LLM returned no questions")
            continue
        for question_index, question in enumerate(questions, 1):
            row_id = f"{id_prefix}_{question_index:02d}"
            if row_id in existing_ids:
                continue
            row = {
                "id": row_id,
                "user_id": chunk["user_id"],
                "question": question,
                "queries": [question],
                "relevant_note_ids": [chunk["note_id"]],
                "relevant_chunk_ids": [chunk["chunk_id"]],
                "relevant_keywords": keywords,
                "label_type": "llm_chunk_question",
                "difficulty": difficulty,
                "review_status": "needs_review",
                "review_hint": (
                    "Check whether the question is naturally answerable from source.text_preview. "
                    "Edit question/keywords or remove this row before using as a final eval sample."
                ),
                "source": {
                    "note_id": chunk["note_id"],
                    "chunk_id": chunk["chunk_id"],
                    "title": chunk.get("title"),
                    "create_time": chunk.get("create_time"),
                    "chunk_index": chunk.get("chunk_index"),
                    "text_preview": chunk.get("text", "")[:700],
                },
            }
            rows.append(row)
            if output:
                _append_jsonl(output, row)
                existing_ids.add(row_id)
        print(f"[{chunk_index}/{total_chunks}] done, wrote {len(questions)} row(s)")
    return rows


def build_llm_dataset(
    *,
    user_ids: list[str],
    per_user: int,
    min_chars: int,
    seed: int,
    queries_per_chunk: int,
    difficulty_plan: dict[str, int] | None = None,
    output: Path | None = None,
    resume: bool = True,
) -> list[dict]:
    return asyncio.run(build_llm_dataset_async(
        user_ids=user_ids,
        per_user=per_user,
        min_chars=min_chars,
        seed=seed,
        queries_per_chunk=queries_per_chunk,
        difficulty_plan=difficulty_plan,
        output=output,
        resume=resume,
    ))


def build_annotation_candidates(
    *,
    query_file: Path,
    top_k: int,
    default_user_id: str | None,
) -> list[dict]:
    rows = []
    for index, item in enumerate(_load_query_rows(query_file), 1):
        question = str(item.get("question") or item.get("query") or "").strip()
        user_id = str(item.get("user_id") or default_user_id or "").strip() or None
        hits = bm25_search(question, user_id=user_id, top_k=top_k)
        rows.append({
            "id": item.get("id") or f"annotate_{index:04d}",
            "user_id": user_id,
            "question": question,
            "queries": item.get("queries") or [question],
            "relevant_note_ids": item.get("relevant_note_ids") or [],
            "relevant_chunk_ids": item.get("relevant_chunk_ids") or [],
            "relevant_keywords": item.get("relevant_keywords") or [],
            "label_type": "manual_required",
            "annotation_hint": "Review candidates and fill relevant_chunk_ids/relevant_note_ids.",
            "candidates": [
                {
                    "rank": rank,
                    "chunk_id": hit.get("chunk_id"),
                    "note_id": hit.get("note_id"),
                    "title": hit.get("title"),
                    "create_time": hit.get("create_time"),
                    "speaker": hit.get("speaker"),
                    "score": hit.get("score"),
                    "text_preview": str(hit.get("text") or "")[:500],
                }
                for rank, hit in enumerate(hits, 1)
            ],
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MeetAgent retrieval dataset files")
    parser.add_argument("--mode", choices=["weak", "llm", "annotate"], default="weak")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--user-id", action="append", default=[], help="User ID; repeat for multiple users.")
    parser.add_argument("--per-user", type=int, default=30, help="Weak samples per selected user.")
    parser.add_argument("--min-chars", type=int, default=300, help="Minimum chunk length for weak samples.")
    parser.add_argument("--keyword-count", type=int, default=5)
    parser.add_argument("--seed", type=int, default=666)
    parser.add_argument("--query-file", default="", help="JSONL or TSV queries for annotate mode.")
    parser.add_argument("--top-k", type=int, default=12, help="Candidate count for annotate mode.")
    parser.add_argument("--queries-per-chunk", type=int, default=1, help="Questions to generate per chunk in llm mode.")
    parser.add_argument(
        "--difficulty-plan",
        default="",
        help="For llm mode, counts such as easy:30,medium:50,hard:20. Overrides --per-user sampling.",
    )
    parser.add_argument("--no-resume", action="store_true", help="For llm mode, do not skip existing row ids.")
    args = parser.parse_args()

    output = Path(args.output)
    if args.mode == "weak":
        if not args.user_id:
            raise SystemExit("--user-id is required for weak mode")
        rows = build_weak_dataset(
            user_ids=args.user_id,
            per_user=args.per_user,
            min_chars=args.min_chars,
            keyword_count=args.keyword_count,
            seed=args.seed,
        )
    elif args.mode == "llm":
        if not args.user_id:
            raise SystemExit("--user-id is required for llm mode")
        difficulty_plan = _parse_difficulty_plan(args.difficulty_plan)
        rows = build_llm_dataset(
            user_ids=args.user_id,
            per_user=args.per_user,
            min_chars=args.min_chars,
            seed=args.seed,
            queries_per_chunk=args.queries_per_chunk,
            difficulty_plan=difficulty_plan or None,
            output=output,
            resume=not args.no_resume,
        )
    else:
        if not args.query_file:
            raise SystemExit("--query-file is required for annotate mode")
        rows = build_annotation_candidates(
            query_file=Path(args.query_file),
            top_k=args.top_k,
            default_user_id=args.user_id[0] if args.user_id else None,
        )

    if args.mode == "llm":
        print(f"Wrote {len(rows)} new rows to {output}")
    else:
        _write_jsonl(output, rows)
        print(f"Wrote {len(rows)} rows to {output}")


if __name__ == "__main__":
    main()
