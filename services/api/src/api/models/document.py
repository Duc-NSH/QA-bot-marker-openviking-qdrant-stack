from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class PageChunk(BaseModel):
    text: str
    section_heading: str | None = None
    page_number: int
    content_type: Literal["text", "table", "figure_caption"]

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be empty")
        return v

    @field_validator("page_number")
    @classmethod
    def page_number_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("page_number must be >= 1")
        return v


class IngestState(BaseModel):
    completed: bool
    pdf_hash: str
    chunk_count: int
    ingested_at: datetime

    @field_validator("chunk_count")
    @classmethod
    def chunk_count_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("chunk_count must be >= 0")
        return v


class ChunkMeta(BaseModel):
    section_heading: str | None
    page_number: int
    content_type: str


class ChunkIndex(BaseModel):
    """Maps chunk filename → Marker metadata for enriching SourceChunk results."""

    entries: dict[str, ChunkMeta] = {}
