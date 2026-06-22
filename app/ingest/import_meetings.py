# -*- coding: utf-8 -*-
import json
import sys
import argparse
from pathlib import Path
from typing import Dict, Optional, Set

from app.storage.db import get_connection, init_db
from app.ingest.chunker import chunk_segments


def import_file(
    json_path: str,
    user_ids: Optional[Set[str]] = None,
    limit_per_user: Optional[int] = None,
    imported_by_user: Optional[Dict[str, int]] = None,
) -> None:
    with open(json_path, encoding="utf-8") as f:
        meetings = json.load(f)

    imported_by_user = imported_by_user if imported_by_user is not None else {}
    conn = get_connection()
    inserted_meetings = 0
    inserted_chunks = 0
    skipped = 0
    filtered = 0
    limited = 0

    for meeting in meetings:
        note_id = meeting.get("note_id")
        if not note_id:
            continue

        user_id = str(meeting.get("userid", ""))
        if user_ids and user_id not in user_ids:
            filtered += 1
            continue
        if limit_per_user is not None and imported_by_user.get(user_id, 0) >= limit_per_user:
            limited += 1
            continue

        existing = conn.execute(
            "SELECT note_id FROM meetings WHERE note_id = ?", (note_id,)
        ).fetchone()
        if existing:
            skipped += 1
            continue

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
        imported_by_user[user_id] = imported_by_user.get(user_id, 0) + 1

    conn.commit()
    conn.close()
    print(
        f"{Path(json_path).name}: {inserted_meetings} meetings, "
        f"{inserted_chunks} chunks, {skipped} skipped, "
        f"{filtered} filtered, {limited} over limit"
    )


def import_directory(
    data_dir: str,
    user_ids: Optional[Set[str]] = None,
    limit_per_user: Optional[int] = None,
) -> None:
    init_db()
    paths = sorted(Path(data_dir).glob("*_meetings.json"))
    if not paths:
        print(f"No *_meetings.json files found in {data_dir}")
        return
    imported_by_user: Dict[str, int] = {}
    for path in paths:
        import_file(
            str(path),
            user_ids=user_ids,
            limit_per_user=limit_per_user,
            imported_by_user=imported_by_user,
        )
    if imported_by_user:
        print("\nImported by user:")
        for user_id, count in sorted(imported_by_user.items()):
            print(f"  {user_id}: {count} meetings")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import meeting JSON files into SQLite")
    parser.add_argument("data_dir", nargs="?", default="test_meetingdata")
    parser.add_argument(
        "--user-id",
        action="append",
        default=[],
        help="Only import this user ID. Can be provided multiple times.",
    )
    parser.add_argument(
        "--limit-per-user",
        type=int,
        default=None,
        help="Maximum new meetings to import per selected user.",
    )
    args = parser.parse_args()
    import_directory(
        args.data_dir,
        user_ids=set(args.user_id) if args.user_id else None,
        limit_per_user=args.limit_per_user,
    )
