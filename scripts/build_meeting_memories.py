# -*- coding: utf-8 -*-
"""Deprecated: meeting facts are no longer copied into long-term memory."""

import argparse


def build_meeting_memories(user_id: str | None = None, min_count: int = 2, limit: int = 50) -> int:
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deprecated no-op. Meeting topics stay in meeting tables.")
    parser.add_argument("--user-id", type=str, default=None)
    parser.add_argument("--min-count", type=int, default=2)
    parser.add_argument("--limit", type=int, default=50)
    parser.parse_args()
    print("No-op: fact/task/topic/decision/risk memories are disabled. Wrote 0 memories.")
