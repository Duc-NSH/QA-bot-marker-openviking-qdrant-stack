import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture()
def mock_qdrant_cls():
    return MagicMock()


@pytest.fixture()
def adapter(mock_qdrant_cls):
    from app.adapters.qdrant import AppQdrantAdapter

    return AppQdrantAdapter(
        sdk_client=mock_qdrant_cls,
        project_name="test",
        collection_name="ctx",
        index_name="default",
        distance_metric="cosine",
    )


def test_physical_collection_name(adapter):
    assert adapter.physical_collection_name == "test__ctx"


def test_from_config():
    cfg = MagicMock()
    cfg.qdrant.url = "http://qdrant:6333"
    cfg.qdrant.api_key = None
    cfg.qdrant.timeout_seconds = 10
    cfg.project_name = "proj"
    cfg.name = "docs"
    cfg.index_name = "default"
    cfg.distance_metric = "cosine"

    with patch("app.adapters.qdrant.QdrantClient"):
        from app.adapters.qdrant import AppQdrantAdapter

        a = AppQdrantAdapter.from_config(cfg)

    assert a._project_name == "proj"
    assert a._collection_name == "docs"
    assert a._index_name == "default"
    assert a.physical_collection_name == "proj__docs"


def test_create_backend_collection_creates_when_new(adapter, mock_qdrant_cls):
    mock_qdrant_cls.collection_exists.return_value = False
    raw_col = MagicMock()
    adapter._new_qdrant_collection = MagicMock(return_value=raw_col)

    adapter._create_backend_collection({})

    mock_qdrant_cls.create_collection.assert_called_once()
    kwargs = mock_qdrant_cls.create_collection.call_args.kwargs
    assert kwargs["collection_name"] == "test__ctx"
    assert kwargs["quantization_config"] is not None


def test_create_backend_collection_creates_marker_payload_indexes(adapter, mock_qdrant_cls):
    mock_qdrant_cls.collection_exists.return_value = False
    raw_col = MagicMock()
    adapter._new_qdrant_collection = MagicMock(return_value=raw_col)

    adapter._create_backend_collection({})

    indexed_fields = {
        call.kwargs["field_name"]
        for call in mock_qdrant_cls.create_payload_index.call_args_list
    }
    assert "section_heading" in indexed_fields
    assert "page_number" in indexed_fields
    assert "content_type" in indexed_fields


def test_create_backend_collection_skips_if_exists(adapter, mock_qdrant_cls):
    mock_qdrant_cls.collection_exists.return_value = True
    raw_col = MagicMock()
    adapter._new_qdrant_collection = MagicMock(return_value=raw_col)

    adapter._create_backend_collection({})

    mock_qdrant_cls.create_collection.assert_not_called()
