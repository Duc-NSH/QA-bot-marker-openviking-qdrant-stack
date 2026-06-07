from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from api.models.document import PageChunk, IngestState
from api.models.query import QueryRequest, QueryResponse, SourceChunk


# --- PageChunk ---

def test_page_chunk_content_type_validation():
    with pytest.raises(ValidationError):
        PageChunk(text="x", section_heading=None, page_number=1, content_type="invalid")


def test_page_chunk_rejects_empty_text():
    with pytest.raises(ValidationError):
        PageChunk(text="   ", section_heading=None, page_number=1, content_type="text")


def test_page_chunk_rejects_zero_page_number():
    with pytest.raises(ValidationError):
        PageChunk(text="x", page_number=0, content_type="text")


def test_page_chunk_rejects_negative_page_number():
    with pytest.raises(ValidationError):
        PageChunk(text="x", page_number=-1, content_type="text")


def test_page_chunk_valid():
    chunk = PageChunk(text="hello", section_heading="S1", page_number=1, content_type="table")
    assert chunk.text == "hello"
    assert chunk.page_number == 1


# --- IngestState ---

def test_ingest_state_roundtrip(tmp_path):
    state = IngestState(
        completed=True,
        pdf_hash="abc123",
        chunk_count=42,
        ingested_at=datetime.now(tz=timezone.utc),
    )
    path = tmp_path / "state.json"
    path.write_text(state.model_dump_json())
    loaded = IngestState.model_validate_json(path.read_text())
    assert loaded.chunk_count == 42
    assert loaded.completed is True
    assert isinstance(loaded.ingested_at, datetime)


def test_ingest_state_accepts_iso_string():
    state = IngestState(
        completed=True,
        pdf_hash="abc",
        chunk_count=1,
        ingested_at="2026-01-01T00:00:00+00:00",
    )
    assert isinstance(state.ingested_at, datetime)


def test_ingest_state_rejects_negative_chunk_count():
    with pytest.raises(ValidationError):
        IngestState(
            completed=True,
            pdf_hash="abc",
            chunk_count=-1,
            ingested_at=datetime.now(tz=timezone.utc),
        )


# --- QueryRequest ---

def test_query_request_defaults():
    req = QueryRequest(question="test")
    assert req.limit == 5


def test_query_request_strips_whitespace():
    req = QueryRequest(question="  hello  ")
    assert req.question == "hello"


def test_query_request_rejects_empty_question():
    with pytest.raises(ValidationError):
        QueryRequest(question="   ")


def test_query_request_rejects_limit_zero():
    with pytest.raises(ValidationError):
        QueryRequest(question="test", limit=0)


def test_query_request_rejects_limit_over_100():
    with pytest.raises(ValidationError):
        QueryRequest(question="test", limit=101)


def test_query_request_accepts_boundary_limits():
    assert QueryRequest(question="test", limit=1).limit == 1
    assert QueryRequest(question="test", limit=100).limit == 100


# --- SourceChunk ---

def test_source_chunk_optional_fields():
    chunk = SourceChunk(uri="viking://test", text="hello", score=0.9)
    assert chunk.section_heading is None
    assert chunk.page_number is None


def test_source_chunk_accepts_score_above_1():
    # OV rescoring can return slightly-over-1.0 scores due to floating-point; must not crash.
    chunk = SourceChunk(uri="viking://test", text="hello", score=1.0001)
    assert chunk.score == 1.0001


def test_source_chunk_rejects_negative_score():
    with pytest.raises(ValidationError):
        SourceChunk(uri="viking://test", text="hello", score=-0.1)


def test_source_chunk_accepts_boundary_scores():
    assert SourceChunk(uri="u", text="t", score=0.0).score == 0.0
    assert SourceChunk(uri="u", text="t", score=1.0).score == 1.0


# --- QueryResponse ---

def test_query_response_has_sources():
    resp = QueryResponse(
        answer="The profit was X",
        sources=[SourceChunk(uri="viking://doc/1", text="profit = X", score=0.95)],
    )
    assert len(resp.sources) == 1
    assert resp.sources[0].score == 0.95
