# AIT Homework — RAG Q&A over MSB Annual Report 2024

A Retrieval-Augmented Generation (RAG) system that answers questions about the BCTN MSB 2024 annual report in Vietnamese. The user types a question; the system retrieves relevant passages from the PDF, then streams a grounded answer via Gemini 2.5 Flash.

---

## Architecture

```mermaid
graph LR
    Browser(["User Browser"])
    Traefik["Traefik - reverse proxy"]

    subgraph Host["Host Machine"]
        MarkerHost["Marker - pre-convert, Metal GPU"]
        Ollama["Ollama - qwen3-embedding"]
        Gemini["Google Gemini 2.5 Flash"]
        PDF["BCTN_MSB_2024.pdf"]
        Vol[("processed_docs volume")]
    end

    subgraph Docker["Docker Compose Stack"]
        Frontend["Frontend - nginx"]
        API["API - FastAPI"]
        MarkerSvc["Marker service - fallback OCR"]
        OV["OpenViking - embedding + retrieval"]
        Qdrant[("Qdrant - vector DB")]
    end

    Browser -->|HTTP| Traefik
    Traefik -->|app.localhost| Frontend
    Traefik -->|api.localhost| API
    Frontend -->|HTTP / SSE| API
    MarkerHost -->|reads| PDF
    MarkerHost -->|chunks + index| Vol
    Vol -->|read on startup| API
    API -->|upload chunks| OV
    API -->|fallback OCR| MarkerSvc
    OV -->|embed text| Ollama
    OV -->|store + search vectors| Qdrant
    API -->|stream LLM answer| Gemini
```

| Service | Image | Role | Docs |
|---|---|---|---|
| `traefik` | `traefik:v3` | Reverse proxy — routes `*.localhost` hostnames | [traefik.md](docs/services/traefik.md) |
| `frontend` | built from `frontend/` | Static HTML/JS chat UI served by nginx | [frontend.md](docs/services/frontend.md) |
| `api` | built from `services/api/` | FastAPI: ingestion, retrieval, streaming Q&A | [api.md](docs/services/api.md) |
| `openviking` | built from `openviking/` | Embedding upload + semantic retrieval | [openviking.md](docs/services/openviking.md) |
| `qdrant` | `qdrant/qdrant:latest` | Vector database | [qdrant.md](docs/services/qdrant.md) |
| `marker` | built from `services/marker/` | PDF OCR via marker-pdf | [marker.md](docs/services/marker.md) |

---

## End-to-End Flow

```mermaid
sequenceDiagram
    actor Dev as Developer
    participant MarkerHost as Marker (host)
    participant Vol as processed_docs volume
    participant API as API (FastAPI)
    participant OV as OpenViking
    participant Ollama as Ollama (host)
    participant Qdrant as Qdrant
    participant Browser as Browser
    participant Gemini as Gemini 2.5 Flash

    rect rgb(220, 235, 255)
        Note over Dev, Vol: Phase 1 - Pre-convert (make pre-convert, run once)
        Dev->>MarkerHost: make pre-convert
        MarkerHost->>MarkerHost: OCR PDF page by page via Surya models
        MarkerHost->>Vol: write chunks/ and chunk_index.json
    end

    rect rgb(220, 255, 220)
        Note over Dev, Qdrant: Phase 2 - Startup and ingestion (make up)
        Dev->>API: make up
        API->>Vol: read ingest_state.json
        alt already completed with same PDF hash
            Note over API: skip ingestion entirely, /health returns ready
        else first run or PDF changed or volumes wiped
            API->>Vol: chunk_index.json found - skip Marker Docker service
            Note right of API: Marker Docker service starts but stays idle
            API->>OV: POST /content/write for each chunk, wait=false
            Note right of OV: returns immediately, embeddings queued async
            par OV embeds asynchronously
                OV->>Ollama: embed chunk text via qwen3-embedding
                Ollama-->>OV: 4096-dim vector
                OV->>Qdrant: store vector
            and API polls Qdrant every 10s
                API->>Qdrant: GET /collections - check points_count
                Qdrant-->>API: current count
            end
            API->>Vol: write ingest_state.json with completed=true
            Note over API: /health returns status ready
        end
    end

    rect rgb(255, 245, 220)
        Note over Browser, Gemini: Phase 3 - Query
        Browser->>API: POST /query with question text
        API->>OV: semantic search with QUERY_PREFIX + question
        OV->>Ollama: embed query text
        Ollama-->>OV: query vector
        OV->>Qdrant: ANN search filtered to bctn collection
        Qdrant-->>OV: top-k matching chunks
        OV-->>API: passages and relevance scores
        API->>Gemini: streaming prompt with retrieved passages
        loop token stream
            Gemini-->>API: next token
            API-->>Browser: SSE token event
        end
        API-->>Browser: SSE done event with full answer and sources
    end
```

---

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Docker Desktop | ≥ 4.30 | Runs all services |
| `uv` | ≥ 0.4 | Python workspace manager |
| Ollama | ≥ 0.3 | Serves `qwen3-embedding` on host |
| A Google API key | — | Enables Gemini 2.5 Flash |

Install `qwen3-embedding` before first run:

```bash
ollama pull qwen3:embedding
```

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url> && cd ait-homework

# 2. Install Python workspace dependencies (for local tooling and type checking)
make dev

# 3. Configure environment
cp .env.example .env
# Edit .env — set GOOGLE_API_KEY

# 4. Generate openviking/ov.conf from the template
make setup

# 5. OCR the PDF on the host (uses Metal GPU; takes ~2.5 hours for full document)
make pre-convert

# 6. Start all Docker services
make up

# 7. Run a smoke-test query
make test
```

Once running, open **http://app.localhost** in your browser.

---

## URLs (local)

| URL | Service |
|---|---|
| http://app.localhost | Chat UI |
| http://api.localhost/health | API health + ingestion status |
| http://api.localhost/docs | FastAPI interactive docs |
| http://openviking.localhost | OpenViking dashboard |
| http://qdrant.localhost | Qdrant REST API |
| http://localhost:8080 | Traefik dashboard |

---

## Make Targets

```
make dev           Install all workspace dependencies into .venv
make setup         Generate openviking/ov.conf from template
make pre-convert   OCR the PDF on host (full GPU + RAM)
make up            Start all services (detached)
make down          Stop services, keep volumes
make clean         Stop services and wipe all volumes (fresh start)
make build         Rebuild Docker images
make logs          Follow all service logs
make logs-api      Follow a specific service's logs
make test          Run smoke-test query against the running stack
make demo-prep     Generate demo_data.json from the live API
make fix-summaries Translate OpenViking L0/L1 summaries to English
```

---

## Configuration

All variables are read from the environment (or `.env`):

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | — | Gemini API key; if unset, Ollama is used for chat |
| `CHAT_MODEL` | `gemini-2.5-flash` | LLM model ID |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama URL |
| `OLLAMA_VLM_MODEL` | `qwen3:14b` | Ollama model for OpenViking doc summaries |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant URL (used by API for ingestion polling) |
| `OPENVIKING_URL` | `http://openviking:1933` | OpenViking base URL |
| `OPENVIKING_API_KEY` | `ait-dev` | OpenViking API key |
| `PDF_PATH` | `/data/BCTN_MSB_2024.pdf` | PDF path inside the API container |
| `PROCESSED_DOCS_PATH` | `/processed_docs` | Volume path for chunks and ingestion state |

See [docs/services/api.md](docs/services/api.md) for LLM backend switching details and [docs/services/openviking.md](docs/services/openviking.md) for VLM configuration.

---

## Running Tests

```bash
# API service tests
uv run --project services/api pytest services/api/tests/ -v

# Marker service tests
uv run --project services/marker pytest services/marker/tests/ -v
```

---

## Service Documentation

Detailed architecture, configuration, and operational notes for each service:

| Service | Document |
|---|---|
| Traefik (reverse proxy) | [docs/services/traefik.md](docs/services/traefik.md) |
| Frontend (chat UI) | [docs/services/frontend.md](docs/services/frontend.md) |
| API (FastAPI backend) | [docs/services/api.md](docs/services/api.md) |
| OpenViking (embedding + retrieval) | [docs/services/openviking.md](docs/services/openviking.md) |
| Qdrant (vector database) | [docs/services/qdrant.md](docs/services/qdrant.md) |
| Marker (PDF OCR) | [docs/services/marker.md](docs/services/marker.md) |
