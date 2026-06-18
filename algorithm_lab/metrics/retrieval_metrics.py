# -*- coding: utf-8 -*-
"""Retrieval metrics for meeting QA experiments."""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class RetrievalMetrics:
    hit_rate: float
    recall: float
    mrr: float
    keyword_hit_rate: float
    result_count: int
    first_hit_rank: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def _relevant_ids(sample: dict, field: str) -> set[str]:
    values = sample.get(field) or []
    return {str(value) for value in values if value}


def _hit_ids(hits: list[dict], field: str) -> list[str]:
    return [str(hit.get(field) or "") for hit in hits]


def _rank_of_first_match(hits: list[dict], sample: dict) -> int | None:
    relevant_chunks = _relevant_ids(sample, "relevant_chunk_ids")
    relevant_notes = _relevant_ids(sample, "relevant_note_ids")

    if not relevant_chunks and not relevant_notes:
        return None

    for rank, hit in enumerate(hits, 1):
        chunk_id = str(hit.get("chunk_id") or "")
        note_id = str(hit.get("note_id") or "")
        if chunk_id in relevant_chunks or note_id in relevant_notes:
            return rank
    return None


def _recall_at_k(hits: list[dict], sample: dict) -> float:
    relevant_chunks = _relevant_ids(sample, "relevant_chunk_ids")
    relevant_notes = _relevant_ids(sample, "relevant_note_ids")

    if relevant_chunks:
        retrieved = set(_hit_ids(hits, "chunk_id"))
        return len(relevant_chunks & retrieved) / len(relevant_chunks)

    if relevant_notes:
        retrieved = set(_hit_ids(hits, "note_id"))
        return len(relevant_notes & retrieved) / len(relevant_notes)

    return 0.0


def _keyword_hit_rate(hits: list[dict], sample: dict) -> float:
    keywords = [str(item).strip() for item in sample.get("relevant_keywords") or [] if str(item).strip()]
    if not keywords:
        return 0.0

    haystack = "\n".join(
        str(hit.get("title") or "") + "\n" + str(hit.get("text") or "")
        for hit in hits
    )
    matched = sum(1 for keyword in keywords if keyword in haystack)
    return matched / len(keywords)


def evaluate_retrieval(hits: list[dict], sample: dict) -> RetrievalMetrics:
    first_hit_rank = _rank_of_first_match(hits, sample)
    has_explicit_labels = bool(
        sample.get("relevant_chunk_ids") or sample.get("relevant_note_ids")
    )
    keyword_hit_rate = _keyword_hit_rate(hits, sample)

    if has_explicit_labels:
        hit_rate = 1.0 if first_hit_rank else 0.0
        recall = _recall_at_k(hits, sample)
        mrr = 1 / first_hit_rank if first_hit_rank else 0.0
    else:
        hit_rate = 1.0 if keyword_hit_rate > 0 else 0.0
        recall = keyword_hit_rate
        mrr = 0.0

    return RetrievalMetrics(
        hit_rate=hit_rate,
        recall=recall,
        mrr=mrr,
        keyword_hit_rate=keyword_hit_rate,
        result_count=len(hits),
        first_hit_rank=first_hit_rank,
    )


def aggregate_metrics(items: list[RetrievalMetrics]) -> dict:
    if not items:
        return {
            "sample_count": 0,
            "hit_rate": 0.0,
            "recall": 0.0,
            "mrr": 0.0,
            "keyword_hit_rate": 0.0,
            "avg_result_count": 0.0,
        }

    return {
        "sample_count": len(items),
        "hit_rate": sum(item.hit_rate for item in items) / len(items),
        "recall": sum(item.recall for item in items) / len(items),
        "mrr": sum(item.mrr for item in items) / len(items),
        "keyword_hit_rate": sum(item.keyword_hit_rate for item in items) / len(items),
        "avg_result_count": sum(item.result_count for item in items) / len(items),
    }
