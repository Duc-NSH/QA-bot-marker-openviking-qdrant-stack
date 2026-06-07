# Marker — PDF OCR Service

## Role

Converts the BCTN MSB 2024 PDF into structured Markdown chunks. Each chunk is one logical section of the document, trimmed to fit within the embedding model's token limit. Marker also produces `chunk_index.json`, which maps filenames to metadata (page number, section heading).

## Two execution modes

### Host-side pre-conversion (recommended)

```bash
make pre-convert
```

Runs `scripts/pre_convert.py` directly on the host using Metal GPU (macOS) or CUDA. This is the normal path — it is significantly faster and produces better OCR quality than the Docker fallback.

Output written to the `processed_docs` Docker volume:
```
/processed_docs/
├── chunks/
│   ├── chunk_0000_p001.md
│   ├── chunk_0001_p001.md
│   ├── ...
│   └── chunk_index.json
└── ingest_state.json          # written by the API after ingestion completes
```

When `chunk_index.json` is present on API startup, the Marker Docker service is bypassed entirely.

### Docker fallback

The `marker` Docker service exists as a fallback for environments without a local GPU. The API calls it at `http://marker:8001/convert` if the pre-converted chunks are not found. It runs the same `marker-pdf` library but inside a container, with reduced batch sizes to avoid OOM:

```yaml
environment:
  RECOGNITION_BATCH_SIZE: "1"
  DETECTOR_BATCH_SIZE: "1"
  TABLE_REC_BATCH_SIZE: "1"
  LAYOUT_BATCH_SIZE: "1"
  FOUNDATION_MODEL_QUANTIZE: "true"
  MARKER_PAGE_RANGE: "0-49"      # processes first 50 pages by default
```

## Image

Built from `services/marker/Dockerfile` — Python 3.13 slim with `marker-pdf` installed via `uv`. CV2 runtime dependencies (`libgl1`, `libglib2.0-0`, etc.) are included.

## Chunk format

Each chunk file begins with the instruction prefix:

```
Represent this financial document passage for retrieval: <markdown content>
```

This prefix is consumed by the embedding model and stripped before display to the user (see `DOC_PREFIX` in `services/api/src/api/constants.py`).

## chunk_index.json

Maps each chunk filename to its metadata:

```json
{
  "entries": {
    "chunk_0020_p006.md": {
      "page_number": 6,
      "section_heading": "Tổng tài sản và tăng trưởng tín dụng"
    },
    ...
  }
}
```

The API uses this at query time to enrich search results with page numbers and section headings for display in the source reference cards.

## Volumes

| Volume | Mount | Contents |
|---|---|---|
| `processed_docs` | `/processed_docs` | Output chunks and index (shared with API) |
| `marker_models` | `/root/.cache` | Downloaded model weights (cached across restarts) |
| `./BCTN_MSB_2024.pdf` | `/data/BCTN_MSB_2024.pdf` | Source PDF (read-only) |

## Networking

Marker is not exposed via Traefik (`traefik.enable=false`). It is reachable only within the Docker network at `http://marker:8001`.
