# Deployment Notes

## Architecture Overview

The stack runs six services coordinated by Docker Compose:

| Service | Image | Role |
|---|---|---|
| `traefik` | `traefik:v3` | Reverse proxy; routes `*.localhost` hostnames |
| `qdrant` | `qdrant/qdrant:latest` | Vector database |
| `openviking` | built from `openviking/` | Embedding + retrieval adapter (wraps Qdrant) |
| `marker` | built from `services/marker/` | PDF OCR via marker-pdf |
| `api` | built from `services/api/` | FastAPI: ingestion, retrieval, streaming QA |
| `frontend` | built from `frontend/` | Static Next.js chat UI |

**LLM backend**: Gemini 2.5 Flash via the OpenAI-compatible API (`/v1beta/openai`). The `GOOGLE_API_KEY` env var is required. Ollama is supported as a fallback (set `OLLAMA_BASE_URL` and `CHAT_MODEL`).

**Embeddings**: `qwen3-embedding` served by Ollama on the host (Metal GPU on Apple Silicon). The API container reaches it via `host.docker.internal`.

## Local Development (macOS / Apple Silicon)

```bash
cp .env.example .env          # set GOOGLE_API_KEY
make pre-convert              # OCR the PDF on host; copies chunks to Docker volume
make up                       # start all Docker services
make test                     # run smoke test
```

### Pre-conversion strategy

`make pre-convert` runs `scripts/pre_convert.py` on the host, which invokes Marker with full Metal GPU access and writes chunk `.md` files + `chunk_index.json` into the `processed_docs` Docker volume. On API startup, when `chunk_index.json` is present, the API skips the Marker OCR step entirely.

This is ~3× faster than running Marker inside Docker (no GPU, limited RAM).

### Ingestion state machine

The API tracks ingestion state in `ingest_state.json` (stored in the `processed_docs` volume). Fields:
- `completed` — `true` once all chunks are uploaded and indexed
- `pdf_hash` — SHA-256 of the source PDF; re-ingestion is skipped if this matches
- `chunk_count` — number of chunks indexed
- `ingested_at` — UTC timestamp (ISO 8601)

The `/health` endpoint returns `status: ready` only after `ingest_state.json` records `completed: true` **and** Qdrant reports at least `chunk_count` vectors. This prevents premature "ready" when embedding is still queued.

### Vector indexing latency

OpenViking uses `wait: false` for embedding uploads — the HTTP call returns immediately, but embedding computation is queued. `qwen3-embedding` via Ollama takes ~40–67 seconds per vector. For the 267-page BCTN 2024 report (320 chunks), full indexing takes ~3–4 hours.

The API's `_wait_for_vectors()` polls Qdrant every 10 seconds and marks ingestion complete only when the actual vector count reaches `chunk_count`.

## Configuration (Environment Variables)

All variables are read by `api/src/api/config.py` via pydantic-settings:

| Variable | Default | Description |
|---|---|---|
| `OPENVIKING_URL` | — | OpenViking base URL |
| `OPENVIKING_API_KEY` | — | API key for OpenViking |
| `MARKER_URL` | — | Marker service base URL |
| `QDRANT_URL` | `http://qdrant:6333` | Direct Qdrant URL for vector count polling |
| `PDF_PATH` | — | Path to the source PDF inside the container |
| `PROCESSED_DOCS_PATH` | — | Base path for chunks and ingestion state |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL (used when `GOOGLE_API_KEY` is unset) |
| `CHAT_MODEL` | `gemini-2.5-flash` | LLM model ID |
| `GOOGLE_API_KEY` | — | Gemini API key; enables Gemini backend |

## Constants (api/src/api/constants.py)

| Constant | Value | Purpose |
|---|---|---|
| `DOC_PREFIX` | `"Represent this financial document passage for retrieval: "` | Prepended to every chunk before indexing |
| `QUERY_PREFIX` | `"Given a user question about a financial report, retrieve relevant passages: "` | Prepended to query text before retrieval |
| `RESOURCES_URI` | `"viking://resources/bctn"` | URI prefix for BCTN document chunks; results with other prefixes are filtered out |
| `GEMINI_BASE_URL` | `"https://generativelanguage.googleapis.com/v1beta/openai"` | Gemini OpenAI-compatible endpoint |

## GPU Server Deployment (NVIDIA)

> **Not yet implemented** — tracked for a future iteration.

Docker on Linux with NVIDIA GPUs can give Marker full GPU access. The required changes are:

1. **Marker Dockerfile** — swap `python:3.13-slim` for a CUDA base image, e.g. `nvidia/cuda:12.4.0-runtime-ubuntu22.04`, and install the CUDA Torch variant.
2. **docker-compose.gpu.yml override** — add GPU reservation:
   ```yaml
   marker:
     deploy:
       resources:
         reservations:
           devices:
             - driver: nvidia
               count: 1
               capabilities: [gpu]
   ```
3. **Host prerequisite** — `nvidia-container-toolkit` must be installed and the Docker daemon configured with `"default-runtime": "nvidia"`.
4. **Run** — `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`

With GPU access, `make pre-convert` can be replaced by letting the marker container handle conversion directly (remove `chunk_index.json` or clear `ingest_state.json`).

## Observability

**Structured JSON logging is implemented.** All services emit JSON logs to stdout with fields: `ts`, `level`, `service`, `logger`, `msg`, plus context extras. Compatible with any log aggregator (Loki, Datadog, CloudWatch).

Full OpenTelemetry tracing is tracked for a future iteration.
