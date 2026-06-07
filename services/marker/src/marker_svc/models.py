from __future__ import annotations

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


class ConvertRequest(BaseModel):
    file_path: str

    @field_validator("file_path")
    @classmethod
    def file_path_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("file_path must not be empty")
        return v.strip()


class ConvertResponse(BaseModel):
    chunks: list[PageChunk]
