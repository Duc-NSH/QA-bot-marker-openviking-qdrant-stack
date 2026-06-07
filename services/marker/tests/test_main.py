from fastapi.testclient import TestClient
from unittest.mock import patch
from marker_svc.main import app
from marker_svc.models import PageChunk

# Patch the heavy model loader so tests run without downloading Surya weights.
_FAKE_MODELS = {"loaded": True}
_PATCH_MODELS = patch("marker.models.create_model_dict", return_value=_FAKE_MODELS)


def test_health():
    with _PATCH_MODELS:
        with TestClient(app) as client:
            resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_convert_file_not_found():
    with _PATCH_MODELS:
        with TestClient(app) as client:
            resp = client.post("/convert", json={"file_path": "/nonexistent_file_abc.pdf"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_convert_returns_chunks(tmp_path):
    fake_pdf = tmp_path / "report.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    mock_chunk = PageChunk(
        text="Test content",
        section_heading="Introduction",
        page_number=1,
        content_type="text",
    )
    with _PATCH_MODELS:
        with patch("marker_svc.main._run_marker", return_value=[mock_chunk]):
            with TestClient(app) as client:
                resp = client.post("/convert", json={"file_path": str(fake_pdf)})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["chunks"]) == 1
    assert data["chunks"][0]["text"] == "Test content"
    assert data["chunks"][0]["page_number"] == 1
