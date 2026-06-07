from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from api.constants import DOC_PREFIX, RESOURCES_URI
from api.models.document import ChunkIndex, ChunkMeta
from api.models.query import QueryRequest, QueryResponse
from api.services.qa import build_sources, stream_answer


@pytest.fixture()
def chunk_index(tmp_path):
    idx = ChunkIndex(entries={
        "chunk_0000_p001.md": ChunkMeta(
            section_heading="Kết quả kinh doanh",
            page_number=1,
            content_type="text",
        )
    })
    path = tmp_path / "chunk_index.json"
    path.write_text(idx.model_dump_json())
    return path


def test_build_sources_matches_filename_to_index(chunk_index):
    ov_resources = [
        {
            "uri": f"{RESOURCES_URI}/chunk_0000_p001.md",
            "score": 0.95,
            "abstract": "profit text",
        }
    ]
    sources = build_sources(ov_resources, chunk_index_path=chunk_index, limit=5)
    assert len(sources) == 1
    assert sources[0].score == 0.95
    assert sources[0].section_heading == "Kết quả kinh doanh"
    assert sources[0].page_number == 1
    assert sources[0].text == "profit text"


def test_build_sources_deduplicates_by_uri(chunk_index):
    ov_resources = [
        {"uri": f"{RESOURCES_URI}/chunk_0000_p001.md", "score": 0.95, "abstract": "a"},
        {"uri": f"{RESOURCES_URI}/chunk_0000_p001.md", "score": 0.80, "abstract": "a"},
    ]
    sources = build_sources(ov_resources, chunk_index_path=chunk_index, limit=5)
    assert len(sources) == 1
    assert sources[0].score == 0.95  # keeps the highest score


def test_build_sources_rejects_non_bctn_uris(chunk_index):
    ov_resources = [
        {"uri": "viking://user/api/.overview.md", "score": 0.99, "abstract": "system doc"},
        {"uri": f"{RESOURCES_URI}/chunk_0000_p001.md", "score": 0.80, "abstract": "bctn"},
    ]
    sources = build_sources(ov_resources, chunk_index_path=chunk_index, limit=5)
    assert len(sources) == 1
    assert RESOURCES_URI in sources[0].uri


def test_build_sources_strips_doc_prefix(chunk_index):
    ov_resources = [
        {
            "uri": f"{RESOURCES_URI}/chunk_0000_p001.md",
            "score": 0.9,
            "abstract": DOC_PREFIX + "actual content",
        }
    ]
    sources = build_sources(ov_resources, chunk_index_path=chunk_index, limit=5)
    assert sources[0].text == "actual content"


async def test_stream_answer_yields_tokens_then_done(chunk_index):
    mock_ov = MagicMock()
    mock_ov.find = AsyncMock(return_value=[
        {"uri": f"{RESOURCES_URI}/chunk_0000_p001.md", "score": 0.9, "abstract": "profit text"}
    ])

    async def fake_stream(*args, **kwargs):
        for token in ["The ", "profit ", "was high."]:
            yield token

    with patch("api.services.qa._openai_stream", new=fake_stream):
        events = []
        async for event_type, data in stream_answer(
            request=QueryRequest(question="What is profit?", limit=3),
            ov_client=mock_ov,
            ollama_base_url="http://host:11434",
            chat_model="gemini-2.5-flash",
            chunk_index_path=chunk_index,
        ):
            events.append((event_type, data))

    token_events = [e for e in events if e[0] == "token"]
    done_events = [e for e in events if e[0] == "done"]
    assert len(token_events) == 3
    assert len(done_events) == 1
    response = QueryResponse.model_validate_json(done_events[0][1])
    assert "profit" in response.answer
    assert len(response.sources) == 1
