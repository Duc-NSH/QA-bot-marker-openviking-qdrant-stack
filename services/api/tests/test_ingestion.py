from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from api.constants import DOC_PREFIX
from api.models.document import PageChunk, IngestState, ChunkIndex
from api.services.ingestion import run_ingestion, _pdf_hash


@pytest.fixture()
def pdf_file(tmp_path):
    p = tmp_path / "test.pdf"
    p.write_bytes(b"%PDF fake content")
    return p


@pytest.fixture()
def mock_marker():
    client = MagicMock()
    client.convert = AsyncMock(return_value=[
        PageChunk(text="content", section_heading="Sec1", page_number=1, content_type="text")
    ])
    return client


@pytest.fixture()
def mock_ov():
    client = MagicMock()
    client.ingest_chunks = AsyncMock(return_value=None)
    return client


async def test_ingestion_skips_when_state_complete(tmp_path, pdf_file, mock_marker, mock_ov):
    state_file = tmp_path / "state.json"
    from datetime import datetime, timezone
    state = IngestState(
        completed=True,
        pdf_hash=_pdf_hash(pdf_file),
        chunk_count=1,
        ingested_at=datetime.now(tz=timezone.utc),
    )
    state_file.write_text(state.model_dump_json())

    with patch("api.services.ingestion._wait_for_vectors", new=AsyncMock()):
        await run_ingestion(
            pdf_path=pdf_file,
            state_path=state_file,
            chunks_dir=tmp_path / "chunks",
            marker_client=mock_marker,
            ov_client=mock_ov,
        )

    mock_marker.convert.assert_not_called()
    mock_ov.ingest_chunks.assert_not_called()


async def test_ingestion_runs_when_no_state(tmp_path, pdf_file, mock_marker, mock_ov):
    state_file = tmp_path / "state.json"
    chunks_dir = tmp_path / "chunks"

    with patch("api.services.ingestion._wait_for_vectors", new=AsyncMock()):
        await run_ingestion(
            pdf_path=pdf_file,
            state_path=state_file,
            chunks_dir=chunks_dir,
            marker_client=mock_marker,
            ov_client=mock_ov,
        )

    mock_marker.convert.assert_called_once_with(str(pdf_file))
    mock_ov.ingest_chunks.assert_called_once()
    assert state_file.exists()
    state = IngestState.model_validate_json(state_file.read_text())
    assert state.completed is True
    assert state.chunk_count == 1


async def test_ingestion_writes_chunk_files_with_prefix(tmp_path, pdf_file, mock_marker, mock_ov):
    chunks_dir = tmp_path / "chunks"

    with patch("api.services.ingestion._wait_for_vectors", new=AsyncMock()):
        await run_ingestion(
            pdf_path=pdf_file,
            state_path=tmp_path / "state.json",
            chunks_dir=chunks_dir,
            marker_client=mock_marker,
            ov_client=mock_ov,
        )

    chunk_files = list(chunks_dir.glob("*.md"))
    assert len(chunk_files) == 1
    content = chunk_files[0].read_text()
    assert content.startswith(DOC_PREFIX)


async def test_ingestion_writes_chunk_index(tmp_path, pdf_file, mock_marker, mock_ov):
    chunks_dir = tmp_path / "chunks"

    with patch("api.services.ingestion._wait_for_vectors", new=AsyncMock()):
        await run_ingestion(
            pdf_path=pdf_file,
            state_path=tmp_path / "state.json",
            chunks_dir=chunks_dir,
            marker_client=mock_marker,
            ov_client=mock_ov,
        )

    index_file = chunks_dir / "chunk_index.json"
    assert index_file.exists()
    index = ChunkIndex.model_validate_json(index_file.read_text())
    assert len(index.entries) == 1


async def test_ingestion_uses_preconverted_chunks(tmp_path, pdf_file, mock_marker, mock_ov):
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    # Pre-populate chunks and index (simulating pre_convert.py)
    (chunks_dir / "chunk_0000_p001.md").write_text(DOC_PREFIX + "pre-converted text")
    index = ChunkIndex(entries={
        "chunk_0000_p001.md": {"section_heading": "S1", "page_number": 1, "content_type": "text"}
    })
    (chunks_dir / "chunk_index.json").write_text(index.model_dump_json())

    with patch("api.services.ingestion._wait_for_vectors", new=AsyncMock()):
        await run_ingestion(
            pdf_path=pdf_file,
            state_path=tmp_path / "state.json",
            chunks_dir=chunks_dir,
            marker_client=mock_marker,
            ov_client=mock_ov,
        )

    # Should skip marker and use pre-converted chunks
    mock_marker.convert.assert_not_called()
    mock_ov.ingest_chunks.assert_called_once()
