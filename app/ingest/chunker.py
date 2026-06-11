# -*- coding: utf-8 -*-
import jieba
from typing import List, Dict

CHUNK_SIZE = 1200
OVERLAP = 150


def tokenize(text: str) -> str:
    return " ".join(jieba.cut(text))


def chunk_segments(segments: List[Dict], note_id: str, user_id: str) -> List[Dict]:
    chunks = []
    chunk_index = 0
    buffer: List[tuple] = []  # list of (speaker, text)
    buffer_len = 0

    for seg in segments:
        speaker = seg.get("speaker", "")
        text = seg.get("text", "").strip()
        if not text:
            continue

        buffer.append((speaker, text))
        buffer_len += len(text)

        if buffer_len >= CHUNK_SIZE:
            chunks.append(_make_chunk(buffer, note_id, user_id, chunk_index))
            chunk_index += 1
            buffer, buffer_len = _trim_to_overlap(buffer)

    if buffer_len > 0:
        chunks.append(_make_chunk(buffer, note_id, user_id, chunk_index))

    return chunks


def _make_chunk(buffer: List[tuple], note_id: str, user_id: str, index: int) -> Dict:
    speakers = list(dict.fromkeys(s for s, _ in buffer))
    text = "".join(t for _, t in buffer)
    return {
        "chunk_id": f"{note_id}:{index:05d}",
        "note_id": note_id,
        "user_id": user_id,
        "chunk_index": index,
        "speaker": ",".join(speakers),
        "text": text,
        "search_text": tokenize(text),
        "char_count": len(text),
    }


def _trim_to_overlap(buffer: List[tuple]):
    total = 0
    result = []
    for speaker, text in reversed(buffer):
        result.insert(0, (speaker, text))
        total += len(text)
        if total >= OVERLAP:
            break
    return result, total
