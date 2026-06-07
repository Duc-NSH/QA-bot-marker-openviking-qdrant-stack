# OpenViking — Embedding and Retrieval

## Role

OpenViking manages the document knowledge base. It receives raw Markdown chunks from the API, stores them in its own file system (AGFS), generates embeddings via Ollama, stores vectors in Qdrant, and serves semantic search queries. It also auto-generates directory-level summaries (L0 abstract, L1 overview) using a VLM.

## Image

Built from `openviking/Dockerfile`, which extends `ghcr.io/volcengine/openviking:latest`:

```dockerfile
FROM ghcr.io/volcengine/openviking:latest
RUN /app/.venv/bin/python -m pip install "qdrant-client>=1.12"
COPY adapter/app /opt/openviking-custom/app
ENV PYTHONPATH="/opt/openviking-custom:${PYTHONPATH:-}"
```

The only additions are `qdrant-client` (for the custom adapter) and the custom adapter itself.

## Custom Qdrant Adapter

Located at `openviking/adapter/app/adapters/qdrant.py`. Registered in `ov.conf` as:

```json
"backend": "app.adapters.qdrant.AppQdrantAdapter"
```

### What `QdrantCollectionAdapter` is

OpenViking's built-in `QdrantCollectionAdapter` is an abstract bridge between OpenViking's internal storage model (`Collection` / `ICollection`) and Qdrant. It handles the bookkeeping that makes OV work: writing OpenViking metadata alongside Qdrant vectors, compiling OV's internal filter format, normalising records on read/write, and managing the meta collection (`__openviking_meta`) that tracks logical collections.

`AppQdrantAdapter` subclasses it and overrides exactly three behaviours. Everything else — OV's AGFS file system layer, L0/L1 abstract generation, content-read/write API plumbing — is inherited unchanged.

### Override 1 — Collection creation (`_create_backend_collection`)

```python
self._sdk_client.create_collection(
    collection_name=self.physical_collection_name,     # "default__bctn_msb"
    vectors_config={"dense": VectorParams(size=4096, distance=Distance.COSINE)},
    quantization_config=ScalarQuantization(
        scalar=ScalarQuantizationConfig(type=ScalarType.INT8, always_ram=True)
    ),
)
```

**`always_ram=True`:** int8 quantization reduces each float32 to one byte — a 4× RAM saving. `always_ram=True` keeps the quantized vectors in RAM even when original float32 vectors are on disk. This is the hot path for the ANN candidate scan, so it must be fast.

**Named vector `"dense"`:** Qdrant supports multiple vector spaces per point (dense + sparse + matryoshka). Naming it `"dense"` lets the adapter and query code refer to it unambiguously (`using="dense"` in `query_points`).

After collection creation, six payload indexes are created:

```python
# From Marker's chunk_index.json metadata
"section_heading" → KEYWORD
"page_number"     → INTEGER
"content_type"    → KEYWORD

# OpenViking's own file-system hierarchy
"uri"         → KEYWORD   # e.g. "viking://resources/bctn/chunk_0020_p006.md"
"parent_uri"  → KEYWORD   # e.g. "viking://resources/bctn/"
"scope_roots" → KEYWORD   # used by OV's directory-scoped search
```

Without these indexes Qdrant falls back to full payload scan for every filtered query. The OV path indexes are what make `target_uri="viking://resources/bctn/"` work efficiently — OV compiles that URI scope into a `parent_uri` filter condition, and Qdrant uses the index to narrow candidates before the ANN step.

The method is **idempotent**: it checks `collection_exists()` before creating, so restarting the stack with an existing Qdrant volume doesn't fail or reset data.

### Override 2 — Query (`query`)

This is the most critical change. The base class uses `search()`. The adapter replaces it with `query_points()` and quantization rescoring:

```python
response = self._sdk_client.query_points(
    ...
    query=query_vector,
    using="dense",
    search_params=SearchParams(
        quantization=QuantizationSearchParams(
            rescore=True,
            oversampling=3.0,
        )
    ),
)
```

**Two-phase retrieval:**

```
Phase 1 — fast, approximate
  query_vector × int8 quantized vectors → top (limit × 3) candidates
  All in RAM. Cheap dot product on bytes, not floats.

Phase 2 — exact rescore
  Reload original float32 vectors for those (limit × 3) candidates only
  Compute true cosine similarity → re-rank → return top `limit`
```

`oversampling=3.0` means: retrieve 3× more candidates from the quantized ANN phase than the final `limit` requested. So a `limit=15` call fetches 45 candidates from int8 ANN, then rescores with float32, returning the true best 15.

**Why this matters for accuracy:** int8 quantization introduces approximation error. A document ranked 6th by quantized similarity might be 2nd by exact similarity. Oversampling + rescoring recovers that accuracy at a fraction of the cost of exact search over all vectors.

**Why OV's default `search()` wasn't enough:** It doesn't pass `QuantizationSearchParams`, so Qdrant uses quantized scores as final scores. For small corpora (228 points, below the HNSW threshold of 10 000) the difference is small, but it becomes significant at scale.

### Override 3 — `upsert`

The base class uses Qdrant's REST batch-write API. This override switches to the Python SDK's `upsert()` and explicitly routes vectors into the named `"dense"` slot:

```python
vector = record.pop("vector", None) or record.pop("dense", None) or []
points.append(
    PointStruct(id=record_id, vector={"dense": vector}, payload=record)
)
```

It also normalises IDs to strings — Qdrant accepts string UUIDs but rejects the integer IDs that OV's internal counters produce.

### Filter translation (`_to_qdrant_filter`)

OV's internal compiled filter format looks like:

```python
{"must": [{"key": "parent_uri", "match": {"value": "viking://resources/bctn/"}}]}
```

The `_to_qdrant_filter()` helper converts this to qdrant-client `Filter` / `FieldCondition` objects. It handles two match types:

- `match.value` → `MatchValue` (exact single-value equality)
- `match.any` → `MatchAny` (IN-list)

This is how `target_uri="viking://resources/bctn/"` in the OV search API becomes a scoped Qdrant filter — OV compiles the URI scope into a `parent_uri` condition, which passes through `_compile_filter()` (inherited), then through this function into native Qdrant syntax.

### Registration and collection naming

```json
"vectordb": { "name": "bctn_msb", "backend": "app.adapters.qdrant.AppQdrantAdapter" }
```

OpenViking loads the backend class by import string at startup. `from_config()` is the factory method called — it reads Qdrant URL, API key, and timeout from config, constructs the `QdrantClient`, and passes it as `sdk_client`. The physical Qdrant collection name is `default__bctn_msb` (project `default` + collection `bctn_msb`).

### Asymmetric retrieval prefixes

```python
DOC_PREFIX   = "Represent this financial document passage for retrieval: "
QUERY_PREFIX = "Given a user question about a financial report, retrieve relevant passages: "
```

`qwen3-embedding` uses instruction-tuned asymmetric embeddings — the same text embedded with different task instructions produces vectors optimised for different roles (document storage vs. query matching). Without task prefixes, all vectors land in a generic instruction-free space and recall degrades noticeably.

These constants are defined here (adapter side, used at embed time) and mirrored in `services/api/src/api/constants.py` (API side, prepended before calling OV search). **Both sides must match exactly** — a mismatch puts documents and queries into misaligned embedding subspaces.

## Configuration (`ov.conf`)

Generated by `make setup` from `openviking/ov.conf.template`. Key sections:

```json
{
  "server": { "host": "0.0.0.0", "port": 1933, "auth_mode": "trusted", "root_api_key": "ait-dev" },
  "storage": {
    "workspace": "/app/.openviking/data",
    "vectordb": { "name": "bctn_msb", "backend": "app.adapters.qdrant.AppQdrantAdapter" },
    "agfs": { "backend": "local" }
  },
  "embedding": {
    "dense": { "provider": "ollama", "model": "qwen3-embedding:latest", "dimension": 4096 },
    "text_source": "content_only",
    "max_input_tokens": 4096
  },
  "vlm": { "provider": "openai", "model": "gemini-2.5-flash", ... },
  "auto_generate_l0": true,
  "auto_generate_l1": true,
  "default_search_mode": "thinking",
  "default_search_limit": 15
}
```

`auth_mode: trusted` means any request is accepted regardless of the API key value — suitable for local development only.

## Volumes

| Volume | Mount | Contents |
|---|---|---|
| `openviking_data` | `/app/.openviking/data` | Chunk files, L0/L1 summaries, internal DB |
| `processed_docs` | `/processed_docs` (read-only) | Chunk files produced by Marker (read at ingest time) |
| `./openviking/ov.conf` | `/app/.openviking/ov.conf` | Runtime config (bind-mount, read-only) |

The AGFS (file system) stores each chunk as a file under:
```
/app/.openviking/data/viking/default/resources/bctn/<filename>.md
```

Directory-level summaries live alongside the chunks as hidden files:
```
/app/.openviking/data/viking/default/resources/bctn/.abstract.md   # L0
/app/.openviking/data/viking/default/resources/bctn/.overview.md   # L1
```

## API usage (from the API service)

```python
# Upload a chunk
POST /api/v1/content/write
{"uri": "viking://resources/bctn/chunk_0001_p001.md", "content": "...", "mode": "create"}

# Semantic search
POST /api/v1/search/find
{"query": "<QUERY_PREFIX> + question", "limit": 15, "target_uri": "viking://resources/bctn/"}

# Read a chunk
GET /api/v1/content/read?uri=viking://resources/bctn/chunk_0001_p001.md

# Read L0 abstract for a directory
GET /api/v1/content/abstract?uri=viking://resources/bctn/
```

## L0/L1 summaries

OpenViking auto-generates a short abstract (L0) and a Markdown overview (L1) for each directory using the configured VLM. Because the chunk content is in Vietnamese (Latin script with diacritics), Gemini sometimes generates summaries in Portuguese instead of English.

To fix this without re-ingesting:

```bash
make fix-summaries
```

This translates the existing summaries via LLM and writes them back using `docker cp` (the `content/write` API rejects writes to derived semantic files like `.abstract.md`).

## Dashboard

Available at **http://openviking.localhost** once the stack is running.

Connection credentials:

| Field | Value |
|---|---|
| URL | `http://openviking.localhost` |
| API Key | `ait-dev` |
| Account | `default` |
| User | `api` |

In `trusted` auth mode the Save button may not complete — this is a known limitation. The data is still visible in the current session.
