from __future__ import annotations

import uuid
from typing import Any, cast

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Condition,
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointIdsList,
    PointStruct,
    QuantizationSearchParams,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    SearchParams,
    VectorParams,
)

from openviking.storage.vectordb.collection.collection import Collection
from openviking.storage.vectordb_adapters import QdrantCollectionAdapter

DOC_PREFIX = "Represent this financial document passage for retrieval: "
QUERY_PREFIX = "Given a user question about a financial report, retrieve relevant passages: "

_EMBEDDING_DIM = 4096
_OVERSAMPLING = 3.0

_MARKER_PAYLOAD_INDEXES: dict[str, PayloadSchemaType] = {
    "section_heading": PayloadSchemaType.KEYWORD,
    "page_number": PayloadSchemaType.INTEGER,
    "content_type": PayloadSchemaType.KEYWORD,
}
_OV_PATH_INDEXES: list[str] = ["uri", "parent_uri", "scope_roots"]


class AppQdrantAdapter(QdrantCollectionAdapter):
    """Custom Qdrant adapter with two-phase quantized retrieval and Marker metadata indexes.

    Registered in ov.conf as:
        "backend": "app.adapters.qdrant.AppQdrantAdapter"

    Extends QdrantCollectionAdapter to inherit Collection/ICollection infrastructure.
    Overrides collection creation to add int8 scalar quantization and Marker payload
    indexes, and overrides query() to use query_points() with quantization rescoring.
    """

    def __init__(self, *, sdk_client: QdrantClient, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sdk_client = sdk_client

    @classmethod
    def from_config(cls, config: Any) -> "AppQdrantAdapter":
        cfg = getattr(config, "qdrant", None) or config
        url = str(getattr(cfg, "url", None) or "http://qdrant:6333")
        api_key = getattr(cfg, "api_key", None)
        timeout = int(getattr(cfg, "timeout_seconds", None) or 10)
        return cls(
            sdk_client=QdrantClient(url=url, api_key=api_key, timeout=timeout),
            url=url.strip().rstrip("/"),
            api_key=api_key,
            timeout_seconds=timeout,
            project_name=str(getattr(config, "project_name", None) or "default"),
            collection_name=str(getattr(config, "name", None) or "context"),
            index_name=str(getattr(config, "index_name", None) or "default"),
            distance_metric=str(getattr(config, "distance_metric", None) or "cosine"),
            dense_vector_name="dense",
            sparse_vector_name="sparse_vector",
            meta_collection_name="__openviking_meta",
            enable_text_index=False,
        )

    @property
    def physical_collection_name(self) -> str:
        return f"{self._project_name}__{self._collection_name}"

    # ── Collection lifecycle ──────────────────────────────────────────────────

    def _create_backend_collection(self, meta: dict[str, Any]) -> Collection:
        """Create Qdrant collection with int8 quantization + Marker payload indexes.

        Idempotent: if the Qdrant collection already exists (e.g. stale from a
        previous broken run), skip creation and just (re-)save OV metadata.
        """
        dist_map = {
            "cosine": Distance.COSINE,
            "l2": Distance.EUCLID,
            "ip": Distance.DOT,
        }
        dist = dist_map.get(self._distance_metric or "cosine", Distance.COSINE)

        if not self._sdk_client.collection_exists(self.physical_collection_name):
            self._sdk_client.create_collection(
                collection_name=self.physical_collection_name,
                vectors_config={"dense": VectorParams(size=_EMBEDDING_DIM, distance=dist)},
                quantization_config=ScalarQuantization(
                    scalar=ScalarQuantizationConfig(type=ScalarType.INT8, always_ram=True)
                ),
            )
            for field, schema_type in _MARKER_PAYLOAD_INDEXES.items():
                self._sdk_client.create_payload_index(
                    collection_name=self.physical_collection_name,
                    field_name=field,
                    field_schema=schema_type,
                )
            for field in _OV_PATH_INDEXES:
                self._sdk_client.create_payload_index(
                    collection_name=self.physical_collection_name,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )

        raw_collection = self._new_qdrant_collection()
        raw_collection._meta_store.save_collection_meta(  # type: ignore[attr-defined]
            collection_key=raw_collection.collection_key,
            logical_collection_name=self._collection_name,
            project_name=self._project_name,
            meta=meta,
        )
        return Collection(raw_collection)

    def _load_existing_collection_if_needed(self) -> None:
        if self._collection is not None:
            return
        raw_collection = self._new_qdrant_collection()
        if not raw_collection.collection_exists():
            return
        if not raw_collection.has_openviking_metadata():
            # Stale Qdrant collection without OV metadata — let create_collection() reinitialize
            return
        self._collection = Collection(raw_collection)

    # ── Data operations ───────────────────────────────────────────────────────

    def upsert(self, data: dict[str, Any] | list[dict[str, Any]]) -> list[str]:
        records = [data] if isinstance(data, dict) else list(data)
        if not records:
            return []
        points: list[PointStruct] = []
        ids: list[str] = []
        for item in records:
            record = dict(self._normalize_record_for_write(item))
            raw_id = record.get("id")
            record_id = str(raw_id) if raw_id is not None else str(uuid.uuid4())
            record["id"] = record_id
            ids.append(record_id)
            vector = record.pop("vector", None) or record.pop("dense", None) or []
            points.append(
                PointStruct(id=record_id, vector={"dense": vector}, payload=record)
            )
        self._sdk_client.upsert(
            collection_name=self.physical_collection_name, points=points
        )
        return ids

    def query(
        self,
        *,
        query_vector: list[float] | None = None,
        sparse_query_vector: dict[str, float] | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        output_fields: list[str] | None = None,
        order_by: str | None = None,
        order_desc: bool = False,
    ) -> list[dict[str, Any]]:
        if not query_vector:
            return []

        compiled = self._compile_filter(filter)
        qdrant_filter = _to_qdrant_filter(compiled) if compiled else None

        response = self._sdk_client.query_points(
            collection_name=self.physical_collection_name,
            query=query_vector,
            using="dense",
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=False,
            query_filter=qdrant_filter,
            search_params=SearchParams(
                quantization=QuantizationSearchParams(
                    rescore=True,
                    oversampling=_OVERSAMPLING,
                )
            ),
        )

        records: list[dict[str, Any]] = []
        for hit in response.points:
            record = dict(hit.payload or {})
            record["id"] = str(hit.id)
            record["_score"] = hit.score
            record = self._normalize_record_for_read(record)
            records.append(record)
        return records

    def delete(
        self,
        *,
        ids: list[str] | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 100_000,
    ) -> int:
        delete_ids = list(ids or [])
        if not delete_ids and filter is not None:
            matched = self.query(filter=filter, limit=limit)
            delete_ids = [r["id"] for r in matched if r.get("id")]
        if delete_ids:
            self._sdk_client.delete(
                collection_name=self.physical_collection_name,
                points_selector=PointIdsList(
                    points=cast(list[Any], delete_ids)
                ),
            )
        return len(delete_ids)

    def count(self, filter: dict[str, Any] | None = None) -> int:
        qdrant_filter: Filter | None = None
        if filter is not None:
            compiled = self._compile_filter(filter)
            qdrant_filter = _to_qdrant_filter(compiled) if compiled else None
        result = self._sdk_client.count(
            collection_name=self.physical_collection_name,
            count_filter=qdrant_filter,
        )
        return result.count


def _to_qdrant_filter(compiled: dict[str, Any] | None) -> Filter | None:
    """Convert OV compiled filter dict to qdrant-client Filter."""
    if not compiled:
        return None
    must_conds: list[Condition] = []
    for cond in compiled.get("must", []):
        key = cond.get("key")
        if not key:
            continue
        match = cond.get("match", {})
        if "value" in match:
            must_conds.append(FieldCondition(key=key, match=MatchValue(value=match["value"])))
        elif "any" in match:
            must_conds.append(FieldCondition(key=key, match=MatchAny(any=match["any"])))
    return Filter(must=must_conds) if must_conds else None
