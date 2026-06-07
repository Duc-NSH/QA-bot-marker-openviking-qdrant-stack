from __future__ import annotations

from pydantic import BaseModel, field_validator


class QueryRequest(BaseModel):
    question: str
    limit: int = 5

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be empty")
        return v.strip()

    @field_validator("limit")
    @classmethod
    def limit_in_range(cls, v: int) -> int:
        if not (1 <= v <= 100):
            raise ValueError("limit must be between 1 and 100")
        return v


class SourceChunk(BaseModel):
    uri: str
    text: str
    score: float
    section_heading: str | None = None
    page_number: int | None = None

    @field_validator("score")
    @classmethod
    def score_in_range(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("score must be >= 0.0")
        return v


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
