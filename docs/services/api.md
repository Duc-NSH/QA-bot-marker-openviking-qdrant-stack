# API — FastAPI Backend

## Role

The central orchestrator. On startup it runs the ingestion pipeline (upload chunks to OpenViking, wait for Qdrant indexing). At query time it performs semantic search via OpenViking, constructs a grounded prompt, and streams the LLM response to the browser as Server-Sent Events.

## Image

Built from `services/api/Dockerfile` — Python 3.13 slim with `uv`. Exposes port 8000.

## Project layout

```
services/api/src/api/
├── main.py          # FastAPI app, lifespan (ingestion task), /health endpoint
├── config.py        # pydantic-settings — all config from environment variables
├── constants.py     # DOC_PREFIX, QUERY_PREFIX, RESOURCES_URI, GEMINI_BASE_URL
├── logger.py        # Structured JSON logging setup
├── routers/
│   └── query.py     # POST /query → SSE stream
├── services/
│   ├── ingestion.py # run_ingestion(), _wait_for_vectors()
│   └── qa.py        # stream_answer(), build_sources()
├── clients/
│   ├── ov_client.py     # OpenViking HTTP client (find, ingest_chunks, ensure_user)
│   └── marker_client.py # Marker HTTP client (convert_pdf fallback)
└── models/
    └── query.py     # QueryRequest, SourceChunk, ChunkIndex Pydantic models
```

## Startup sequence

1. `lifespan()` creates the `OVClient` and `MarkerClient`.
2. Spawns `run_ingestion()` as a background `asyncio.Task`.
3. `/health` returns `{"status": "indexing"}` until ingestion completes.

## Ingestion pipeline (`services/ingestion.py`)

```
read ingest_state.json
  ├─ completed=true AND pdf_hash matches → skip (idempotent)
  └─ otherwise:
       ├─ chunk_index.json present → use pre-converted chunks
       └─ otherwise → call Marker Docker service to convert PDF
       │
       ▼
       upload all chunks to OpenViking (create-or-replace, wait=false)
       │
       ▼
       _wait_for_vectors(): poll Qdrant every 10s until
           points_count == expected_chunk_count
       │
       ▼
       write ingest_state.json { completed: true, pdf_hash: ... }
```

## Query pipeline (`services/qa.py`)

```
POST /query { question, limit }
  │
  ├─ yield SSE event: status="searching"
  ├─ OVClient.find(question, limit × 3)   # over-fetch then re-rank
  ├─ build_sources(): read chunk files, enrich with chunk_index metadata
  │
  ├─ yield SSE event: status="generating"
  ├─ stream LLM (Gemini or Ollama)
  │     yields SSE event: token="<text>"  per chunk
  │
  └─ yield SSE event: done={ answer, sources }
```

`build_sources()` always reads source text from the chunk files on disk (Vietnamese content) rather than from OpenViking's auto-generated abstracts (which may be in Portuguese).

## LLM backends

The backend is selected at runtime based on `GOOGLE_API_KEY`:

| Condition | Backend | Base URL |
|---|---|---|
| `GOOGLE_API_KEY` is set | Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `GOOGLE_API_KEY` is unset | Ollama | `$OLLAMA_BASE_URL/v1` |

Both backends use the OpenAI-compatible `/chat/completions` endpoint with `stream=true`. The timeout is 300 seconds (5 minutes).

## SSE event types

| Event | Data | Description |
|---|---|---|
| `status` | `"searching"` or `"generating"` | Progress indicator |
| `token` | `"<text fragment>"` | One LLM output token |
| `done` | `{"answer": "...", "sources": [...]}` | Full answer + source list |
| `error` | `{"message": "...", "detail": "..."}` | Error description |

## Configuration

All settings are read from environment variables via `pydantic-settings` (`config.py`):

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | — | If set, uses Gemini; otherwise Ollama |
| `CHAT_MODEL` | `gemini-2.5-flash` | LLM model identifier |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama URL |
| `OPENVIKING_URL` | `http://openviking:1933` | OpenViking base URL |
| `OPENVIKING_API_KEY` | `ait-dev` | OpenViking API key |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant URL (for polling during ingestion) |
| `PDF_PATH` | `/data/BCTN_MSB_2024.pdf` | PDF path inside container |
| `PROCESSED_DOCS_PATH` | `/processed_docs` | Volume path for chunks and state |

## Volumes

| Volume | Mount | Contents |
|---|---|---|
| `processed_docs` | `/processed_docs` | Chunks, chunk_index.json, ingest_state.json |
| `./BCTN_MSB_2024.pdf` | `/data/BCTN_MSB_2024.pdf` | Source PDF (read-only) |

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | `{"status": "ready"/"indexing", "error": null}` |
| `POST` | `/query` | SSE stream — semantic search + LLM answer |
| `GET` | `/docs` | FastAPI interactive documentation |
