import pytest
import respx
import httpx
from api.models.document import PageChunk
from api.clients.marker_client import MarkerClient, MarkerError
from api.clients.ov_client import OVClient, OVClientError
from api.constants import RESOURCES_URI


@pytest.fixture()
def marker_client():
    return MarkerClient(base_url="http://marker:8001")


@pytest.fixture()
def ov_client():
    return OVClient(base_url="http://openviking:1933")


@respx.mock
async def test_marker_client_convert(marker_client):
    respx.post("http://marker:8001/convert").mock(return_value=httpx.Response(
        200,
        json={"chunks": [{"text": "hello", "section_heading": "S1",
                          "page_number": 1, "content_type": "text"}]},
    ))
    chunks = await marker_client.convert("/data/file.pdf")
    assert len(chunks) == 1
    assert isinstance(chunks[0], PageChunk)
    assert chunks[0].text == "hello"


@respx.mock
async def test_marker_client_raises_marker_error_on_404(marker_client):
    respx.post("http://marker:8001/convert").mock(return_value=httpx.Response(
        404, json={"detail": "File not found"}
    ))
    with pytest.raises(MarkerError):
        await marker_client.convert("/nonexistent.pdf")


@respx.mock
async def test_ov_client_find(ov_client):
    respx.post("http://openviking:1933/api/v1/search/find").mock(
        return_value=httpx.Response(200, json={"result": {
            "resources": [{"uri": f"{RESOURCES_URI}/chunk_0001_p001.md", "score": 0.9,
                            "abstract": "profit text", "level": 2,
                            "context_type": "resource"}],
            "memories": [], "skills": [], "total": 1,
        }})
    )
    results = await ov_client.find("what is profit?", limit=5)
    assert len(results) == 1
    assert results[0]["uri"] == f"{RESOURCES_URI}/chunk_0001_p001.md"
    assert results[0]["score"] == 0.9


@respx.mock
async def test_ov_client_find_raises_on_error(ov_client):
    respx.post("http://openviking:1933/api/v1/search/find").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )
    with pytest.raises(OVClientError):
        await ov_client.find("query")
