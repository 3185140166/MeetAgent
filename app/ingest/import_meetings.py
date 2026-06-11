# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

from app.storage.db import get_connection, init_db
from app.ingest.chunker import chunk_segments


def import_file(json_path: str) -> None:
    with open(json_path, encoding="utf-8") as f:
        meetings = json.load(f)

    conn = get_connection()
    inserted_meetings = 0
    inserted_chunks = 0
    skipped = 0

    for meeting in meetings:
        note_id = meeting.get("note_id")
        if not note_id:
            continue

        existing = conn.execute(
            "SELECT note_id FROM meetings WHERE note_id = ?", (note_id,)
        ).fetchone()
        if existing:
            skipped += 1
            continue

        user_id = meeting.get("userid", "")
        conn.execute(
            """
            INSERT INTO meetings
              (note_id, user_id, title, create_time, duration_minutes,
               language, audio_id, audio_path, raw_json_path, asr_result_length)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note_id,
                user_id,
                meeting.get("title", ""),
                meeting.get("create_time", ""),
                meeting.get("duration_minutes"),
                meeting.get("language", ""),
                meeting.get("audio_id", ""),
                meeting.get("audio_full_path", ""),
                str(json_path),
                meeting.get("asr_result_length"),
            ),
        )
        inserted_meetings += 1

        segments = meeting.get("asr_segment", [])
        for chunk in chunk_segments(segments, note_id, user_id):
            conn.execute(
                """
                INSERT INTO chunks
                  (chunk_id, note_id, user_id, chunk_index, speaker, text, search_text, char_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk["chunk_id"],
                    chunk["note_id"],
                    chunk["user_id"],
                    chunk["chunk_index"],
                    chunk["speaker"],
                    chunk["text"],
                    chunk["search_text"],
                    chunk["char_count"],
                ),
            )
            conn.execute(
                """
                INSERT INTO fts_chunks (chunk_id, note_id, user_id, search_text)
                VALUES (?, ?, ?, ?)
                """,
                (chunk["chunk_id"], chunk["note_id"], chunk["user_id"], chunk["search_text"]),
            )
            inserted_chunks += 1

    conn.commit()
    conn.close()
    print(f"{Path(json_path).name}: {inserted_meetings} meetings, {inserted_chunks} chunks, {skipped} skipped")


def import_directory(data_dir: str) -> None:
    init_db()
    paths = sorted(Path(data_dir).glob("*_meetings.json"))
    if not paths:
        print(f"No *_meetings.json files found in {data_dir}")
        return
    for path in paths:
        import_file(str(path))


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "test_meetingdata"
    import_directory(data_dir)
