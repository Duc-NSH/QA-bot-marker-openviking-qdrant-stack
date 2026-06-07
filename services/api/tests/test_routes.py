import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture()
def docs_dir(tmp_path):
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    (chunks / "chunk_index.json").write_text('{"entries": {}}')
    return tmp_path


@pytest.fixture()
def client(docs_dir):
    # Patch ingestion so startup doesn't actually run OCR
    with patch("api.main.run_ingestion", new_callable=AsyncMock), \
         patch("api.main.settings") as mock_settings:
        mock_settings.pdf_path = "/nonexistent.pdf"
        mock_settings.processed_docs_path = str(docs_dir)
        mock_settings.openviking_url = "http://openviking:1933"
        mock_settings.marker_url = "http://marker:8001"
        mock_settings.ollama_base_url = "http://host:11434"
        mock_settings.chat_model = "qwen3:14b"
        mock_settings.qdrant_url = "http://qdrant:6333"
        mock_settings.google_api_key = None
        from api.main import app
        with TestClient(app) as c:
            yield c


def test_health_ready(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ready", "indexing")


def test_query_streams_events(client):
    async def fake_stream(*args, **kwargs):
        yield "token", "hello"
        yield "done", '{"answer":"hello","sources":[]}'

    with patch("api.routers.query.stream_answer", side_effect=fake_stream):
        with client.stream("POST", "/query", json={"question": "test", "limit": 3}) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            body = resp.read().decode()
    assert "event: token" in body
    assert "event: done" in body


def test_query_requires_question(client):
    resp = client.post("/query", json={})
    assert resp.status_code == 422


def test_query_returns_503_when_index_missing(tmp_path):
    with patch("api.main.run_ingestion", new_callable=AsyncMock), \
         patch("api.main.settings") as mock_settings:
        mock_settings.pdf_path = "/nonexistent.pdf"
        mock_settings.processed_docs_path = str(tmp_path)  # no chunks/ dir created
        mock_settings.openviking_url = "http://openviking:1933"
        mock_settings.marker_url = "http://marker:8001"
        mock_settings.ollama_base_url = "http://host:11434"
        mock_settings.chat_model = "qwen3:14b"
        mock_settings.qdrant_url = "http://qdrant:6333"
        mock_settings.google_api_key = None
        from api.main import app
        with TestClient(app) as c:
            resp = c.post("/query", json={"question": "test"})
            assert resp.status_code == 503
