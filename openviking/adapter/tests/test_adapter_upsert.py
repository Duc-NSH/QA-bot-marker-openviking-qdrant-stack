import pytest
from unittest.mock import MagicMock


@pytest.fixture()
def adapter():
    from app.adapters.qdrant import AppQdrantAdapter

    return AppQdrantAdapter(
        sdk_client=MagicMock(),
        project_name="test",
        collection_name="ctx",
        index_name="default",
        distance_metric="cosine",
    )


def test_upsert_single_record(adapter):
    ids = adapter.upsert({
        "id": "abc",
        "vector": [0.1, 0.2, 0.3, 0.4],
        "uri": "viking://test/chunk1",
        "section_heading": "Intro",
        "page_number": 1,
        "content_type": "text",
    })
    assert ids == ["abc"]
    adapter._sdk_client.upsert.assert_called_once()
    points = adapter._sdk_client.upsert.call_args.kwargs["points"]
    assert points[0].id == "abc"
    assert "dense" in points[0].vector
    assert points[0].vector["dense"] == [0.1, 0.2, 0.3, 0.4]
    assert points[0].payload["section_heading"] == "Intro"
    assert points[0].payload["page_number"] == 1


def test_upsert_generates_id_when_missing(adapter):
    ids = adapter.upsert({"vector": [0.1, 0.2, 0.3, 0.4]})
    assert len(ids) == 1
    assert len(ids[0]) == 36  # UUID format


def test_upsert_batch(adapter):
    records = [
        {"id": f"id{i}", "vector": [float(i)] * 4} for i in range(3)
    ]
    ids = adapter.upsert(records)
    assert ids == ["id0", "id1", "id2"]
    points = adapter._sdk_client.upsert.call_args.kwargs["points"]
    assert len(points) == 3


def test_upsert_empty_does_nothing(adapter):
    ids = adapter.upsert([])
    assert ids == []
    adapter._sdk_client.upsert.assert_not_called()


def test_delete_by_ids(adapter):
    n = adapter.delete(ids=["a", "b"])
    assert n == 2
    adapter._sdk_client.delete.assert_called_once()


def test_count_returns_int(adapter):
    adapter._sdk_client.count.return_value = MagicMock(count=42)
    assert adapter.count() == 42
