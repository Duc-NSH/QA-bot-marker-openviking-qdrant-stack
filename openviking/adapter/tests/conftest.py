"""
Stubs openviking package so adapter tests run without installing openviking
(which requires Rust compilation).
"""
import sys
from typing import Any
from unittest.mock import MagicMock


class _StubQdrantCollectionAdapter:
    """Minimal replica of openviking QdrantCollectionAdapter.

    Sets the attributes that AppQdrantAdapter reads from its parent, and
    provides a _new_qdrant_collection() stub so _create_backend_collection()
    can call it without hitting the real openviking internals.
    """

    _URI_FIELD_NAMES: set[str] = {"uri", "parent_uri"}

    def __init__(
        self,
        *,
        project_name: str = "default",
        collection_name: str = "context",
        index_name: str = "default",
        distance_metric: str = "cosine",
        **_kwargs: Any,
    ) -> None:
        self._project_name = project_name
        self._collection_name = collection_name
        self._index_name = index_name
        self._distance_metric = distance_metric
        self._collection: Any = None

    def _normalize_record_for_write(self, record: dict[str, Any]) -> dict[str, Any]:
        return dict(record)

    def _normalize_record_for_read(self, record: dict[str, Any]) -> dict[str, Any]:
        return dict(record)

    def _compile_filter(self, expr: Any) -> dict[str, Any]:
        if isinstance(expr, dict):
            return expr
        return {}

    @classmethod
    def from_config(cls, config: Any) -> "_StubQdrantCollectionAdapter":
        raise NotImplementedError

    def _load_existing_collection_if_needed(self) -> None:
        pass

    def _create_backend_collection(self, meta: dict[str, Any]) -> Any:
        raise NotImplementedError

    def _new_qdrant_collection(self) -> MagicMock:
        return MagicMock()


_stub_vectordb_adapters = MagicMock()
_stub_vectordb_adapters.QdrantCollectionAdapter = _StubQdrantCollectionAdapter

_stub_errors = MagicMock()
_stub_errors.CollectionNotFoundError = ValueError

for mod, obj in [
    ("openviking", MagicMock()),
    ("openviking.storage", MagicMock()),
    ("openviking.storage.vectordb_adapters", _stub_vectordb_adapters),
    ("openviking.storage.vectordb.collection", MagicMock()),
    ("openviking.storage.vectordb.collection.collection", MagicMock()),
    ("openviking.storage.errors", _stub_errors),
]:
    sys.modules.setdefault(mod, obj)
