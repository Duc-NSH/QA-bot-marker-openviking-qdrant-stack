# Qdrant — Vector Database

## Role

Stores and searches the 4096-dimensional embeddings produced by `qwen3-embedding`. It is the persistence layer for all vectorised chunk content and is accessed exclusively through OpenViking — the API service never writes to Qdrant directly.

## Image

`qdrant/qdrant:latest` — official image, no customisation.

## Storage

Data persists in the `qdrant_data` named Docker volume, mounted at `/qdrant/storage` inside the container. Wiping this volume (via `make clean`) forces full re-embedding on the next `make up`.

## Collection

The collection is created and owned by OpenViking (via `AppQdrantAdapter`). The physical name in Qdrant is `default__bctn_msb` — OV prefixes the project name (`default`) to the logical collection name from `ov.conf` (`bctn_msb`).

| Parameter | Value | Reason |
|---|---|---|
| Physical name | `default__bctn_msb` | OV project prefix + logical name |
| Vector dimension | 4096 | `qwen3-embedding` output size |
| Distance metric | Cosine | Standard for normalised text embeddings |
| Quantization | int8 scalar, `always_ram=True` | 4× RAM saving; quantized copy kept in RAM for fast ANN |
| HNSW index threshold | 10 000 points | Below this, Qdrant uses brute-force exact search |

For the BCTN MSB 2024 corpus (228 chunks) the HNSW graph is never built. Qdrant performs exact search over all 228 quantized vectors — then rescores with float32 via the adapter's `oversampling=3.0` setting. At this scale exact search is faster than HNSW graph traversal anyway.

## Quantization detail

int8 scalar quantization converts each float32 component of a 4096-dim vector into a signed 8-bit integer. Storage drops from `4096 × 4 = 16 384` bytes per vector to `4096 × 1 = 4096` bytes — a 4× reduction.

`always_ram=True` (set in `AppQdrantAdapter._create_backend_collection`) tells Qdrant to keep this int8 copy in RAM at all times, even if the original float32 vectors are memory-mapped from disk. This matters because Phase 1 of every search (the ANN candidate scan) operates entirely on the int8 copy.

**Phase 1 — fast approximate scan (int8):**
Dot products over byte integers are significantly cheaper than over float32. Qdrant scans all 228 int8 vectors and returns the top `limit × 3` candidates (e.g. 45 for a `limit=15` query).

**Phase 2 — exact rescore (float32):**
The original float32 vectors for only those 45 candidates are loaded and true cosine similarity is computed. The top 15 by exact score are returned to OpenViking.

The oversampling factor of 3 is the tradeoff knob: higher → better recall at the cost of more float32 rescoring work. For 228 vectors the cost is negligible; at 100 000+ vectors the choice of this value becomes meaningful.

## Payload indexes

Every point stored by OV carries a payload — a JSON dict of metadata fields. Qdrant can filter by payload fields during search, but without an index it scans all payloads linearly. `AppQdrantAdapter._create_backend_collection` creates six indexes at collection creation time:

| Field | Type | Purpose |
|---|---|---|
| `section_heading` | keyword | Filter or display by document section |
| `page_number` | integer | Filter or display by page |
| `content_type` | keyword | Filter by chunk content type (text, table, etc.) |
| `uri` | keyword | OV: identify a specific chunk by its full Viking URI |
| `parent_uri` | keyword | OV: scope search to a directory (`target_uri` filter) |
| `scope_roots` | keyword | OV: internal hierarchy traversal |

The three OV path indexes are essential for directory-scoped search. When the API calls:

```python
POST /api/v1/search/find
{"query": "...", "target_uri": "viking://resources/bctn/"}
```

OV compiles this into a `parent_uri` filter condition, which passes through `_to_qdrant_filter()` and reaches Qdrant as a `FieldCondition(key="parent_uri", match=MatchValue(value="viking://resources/bctn/"))`. Without the index, every search would scan all payloads regardless of how many collections or directories existed.

## What each point contains

A Qdrant point for one chunk has:

```
id      — string UUID (normalised from OV's internal integer ID)
vector  — {"dense": [4096 × float32]}   (stored on disk, compressed)
payload — {
    "uri":             "viking://resources/bctn/chunk_0020_p006.md",
    "parent_uri":      "viking://resources/bctn/",
    "scope_roots":     ["viking://resources/bctn/"],
    "section_heading": "Tổng tài sản và tăng trưởng tín dụng",
    "page_number":     6,
    "content_type":    "text",
    ... other OV internal fields ...
}
```

The `section_heading` and `page_number` fields originate from `chunk_index.json` produced by Marker and are injected by the API during ingestion (passed as metadata alongside the chunk content in the `content/write` call to OV, which forwards them as Qdrant payload).

## Ingestion progress

The API service polls Qdrant directly during ingestion to track embedding progress. OV's `content/write` API returns immediately (`wait=false`) and embeds asynchronously, so the only reliable way to know when all vectors are stored is to watch `points_count`:

```
GET http://qdrant:6333/collections/default__bctn_msb
→ result.points_count          # increments as OV embeds each chunk
→ result.indexed_vectors_count # HNSW index; stays 0 below the 10 000 threshold
```

The API polls every 10 seconds and considers ingestion complete when `points_count` reaches the expected chunk count (228 for the full BCTN MSB 2024 report). `indexed_vectors_count` is never used as the completion signal — at 228 chunks it stays 0 permanently because the HNSW threshold is never crossed.

## Networking

- Internal: `http://qdrant:6333` (Docker network, used by OpenViking and API)
- External: `http://qdrant.localhost` (via Traefik, for inspection)

The API accesses Qdrant directly only for ingestion progress polling. All search traffic goes through OpenViking, never directly to Qdrant.

## Useful endpoints

```bash
# Collection summary (includes points_count, config, quantization params)
curl http://qdrant.localhost/collections/default__bctn_msb | python3 -m json.tool

# Watch ingestion progress
watch -n 5 'curl -s http://qdrant.localhost/collections/default__bctn_msb \
  | python3 -c "import json,sys; r=json.load(sys.stdin)[\"result\"]; \
    print(r[\"points_count\"], \"/ 228 points\")"'

# Inspect a specific point's payload
curl "http://qdrant.localhost/collections/default__bctn_msb/points/<uuid>"
```
