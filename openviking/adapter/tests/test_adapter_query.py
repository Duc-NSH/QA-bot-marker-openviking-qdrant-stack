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


def test_query_uses_oversampling(adapter):
    adapter._sdk_client.query_points.return_value = MagicMock(points=[])
    adapter.query(query_vector=[0.1, 0.2, 0.3, 0.4], limit=5)

    kwargs = adapter._sdk_client.query_points.call_args.kwargs
    qparams = kwargs["search_params"].quantization
    assert qparams.rescore is True
    assert qparams.oversampling == 3.0


def test_query_uses_dense_vector(adapter):
    adapter._sdk_client.query_points.return_value = MagicMock(points=[])
    adapter.query(query_vector=[0.1, 0.2, 0.3, 0.4], limit=5)

    kwargs = adapter._sdk_client.query_points.call_args.kwargs
    assert kwargs["query"] == [0.1, 0.2, 0.3, 0.4]
    assert kwargs["using"] == "dense"


def test_query_returns_records_with_score(adapter):
    hit = MagicMock()
    hit.id = "abc"
    hit.score = 0.95
    hit.payload = {"uri": "viking://test/doc", "text": "hello"}
    adapter._sdk_client.query_points.return_value = MagicMock(points=[hit])

    results = adapter.query(query_vector=[0.1, 0.2, 0.3, 0.4], limit=5)

    assert len(results) == 1
    assert results[0]["_score"] == 0.95
    assert results[0]["id"] == "abc"


def test_query_empty_vector_returns_empty(adapter):
    results = adapter.query(query_vector=None, limit=5)
    assert results == []
    adapter._sdk_client.query_points.assert_not_called()


def test_to_qdrant_filter_equality():
    from app.adapters.qdrant import _to_qdrant_filter

    f = _to_qdrant_filter({"must": [{"key": "uri", "match": {"value": "viking://test"}}]})
    assert f is not None
    assert f.must[0].key == "uri"
    assert f.must[0].match.value == "viking://test"


def test_to_qdrant_filter_any():
    from app.adapters.qdrant import _to_qdrant_filter

    f = _to_qdrant_filter({"must": [{"key": "scope_roots", "match": {"any": ["/", "/docs"]}}]})
    assert f is not None
    assert f.must[0].match.any == ["/", "/docs"]


def test_to_qdrant_filter_empty_returns_none():
    from app.adapters.qdrant import _to_qdrant_filter

    assert _to_qdrant_filter({}) is None
    assert _to_qdrant_filter(None) is None
