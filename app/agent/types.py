# -*- coding: utf-8 -*-
"""Shared Agent result types."""

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Source:
    source_id: str
    note_id: str = ""
    chunk_id: str = ""
    meeting_title: str = ""
    create_time: str = ""
    speaker: str = ""
    quote: str = ""
    score: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ToolResult:
    ok: bool
    tool: str
    text_for_llm: str
    data: Any = None
    sources: list[Source] = field(default_factory=list)
    error: Optional[str] = None

    def sources_as_dict(self) -> list[dict]:
        return [source.to_dict() for source in self.sources]
