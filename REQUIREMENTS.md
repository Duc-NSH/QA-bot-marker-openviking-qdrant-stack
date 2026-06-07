# System Requirements

This document describes the functional and non-functional requirements for the AIT Homework RAG system.

---

## 1. Functional Requirements

### 1.1 Document Ingestion

| ID | Requirement |
|---|---|
| F-ING-01 | The system shall accept a PDF document as the knowledge source. |
| F-ING-02 | The system shall extract text from every page of the PDF using an OCR pipeline (Marker + Surya). |
| F-ING-03 | Extracted text shall be split into page-level chunks, each carrying metadata: page number, section heading, and content type. |
| F-ING-04 | Each chunk shall be prefixed with a document-context instruction string before being sent to the embedding model (asymmetric retrieval). |
| F-ING-05 | The system shall upload chunks to the vector store via the OpenViking API. |
| F-ING-06 | The system shall poll the vector store until the indexed point count reaches the expected chunk count before marking ingestion complete. |
| F-ING-07 | Ingestion state (completion flag, PDF hash, chunk count, timestamp) shall be persisted to disk so that re-ingestion of an unchanged PDF is skipped on restart. |
| F-ING-08 | The system shall support a pre-conversion mode where OCR runs on the host machine (with GPU access) and the resulting chunks are read directly by the API container, bypassing the in-container Marker service. |

### 1.2 Retrieval

| ID | Requirement |
|---|---|
| F-RET-01 | The system shall accept a natural-language question and return semantically relevant document passages. |
| F-RET-02 | Query text shall be prefixed with a query-context instruction string before embedding (asymmetric retrieval, matching F-ING-04). |
| F-RET-03 | Retrieval results shall be filtered to the document collection URI prefix (`viking://resources/bctn`), excluding any vector-store internal documents. |
| F-RET-04 | The number of retrieved passages shall be configurable per request (default: 5, range: 1–100). |
| F-RET-05 | Each retrieved passage shall carry a relevance score (0.0–1.0), source URI, and page number. |

### 1.3 Question Answering

| ID | Requirement |
|---|---|
| F-QA-01 | The system shall generate a grounded answer by passing retrieved passages as context to a large language model. |
| F-QA-02 | The answer shall be streamed token-by-token to the client using Server-Sent Events (SSE). |
| F-QA-03 | The SSE stream shall emit a `token` event for each answer fragment and a `done` event carrying the final answer and source list. |
| F-QA-04 | The primary LLM backend shall be Google Gemini 2.5 Flash via its OpenAI-compatible endpoint. |
| F-QA-05 | When no Google API key is configured, the system shall fall back to a locally served Ollama model. |

### 1.4 API

| ID | Requirement |
|---|---|
| F-API-01 | The system shall expose a `POST /query` endpoint accepting `{ question: string, limit?: int }`. |
| F-API-02 | The system shall expose a `GET /health` endpoint returning `{ status: "ready" \| "indexing" \| "error" }`. |
| F-API-03 | `/query` shall return HTTP 503 while ingestion is incomplete (chunk index not yet present). |
| F-API-04 | `/query` shall return HTTP 422 for malformed requests (missing or blank question). |
| F-API-05 | All request/response models shall be validated by Pydantic v2 with explicit field constraints. |

### 1.5 Frontend

| ID | Requirement |
|---|---|
| F-FE-01 | The system shall provide a web-based chat interface for submitting questions and displaying streamed answers. |
| F-FE-02 | The UI shall display source passages (URI, page number, relevance score) alongside each answer. |
| F-FE-03 | The UI shall indicate loading state while the answer is streaming. |

---

## 2. Non-Functional Requirements

### 2.1 Performance

| ID | Requirement |
|---|---|
| NF-PERF-01 | First token of a streamed answer shall appear within 10 seconds of a query request under normal load. |
| NF-PERF-02 | The OCR pre-conversion of the 267-page BCTN 2024 report shall complete within 3 hours on a host with Apple Silicon GPU (Metal). |
| NF-PERF-03 | Vector embedding of 228 chunks shall complete within 4 hours using `qwen3-embedding` served by Ollama on Apple Silicon. |

### 2.2 Reliability

| ID | Requirement |
|---|---|
| NF-REL-01 | The API shall not report `status: ready` until the Qdrant point count equals the ingested chunk count, preventing queries against a partially indexed collection. |
| NF-REL-02 | All Docker services shall define health checks; dependent services shall wait for their dependencies to be healthy before starting. |
| NF-REL-03 | Ingestion shall be idempotent: re-running with the same PDF (same SHA-256 hash) shall not re-index or overwrite the existing vector store. |

### 2.3 Observability

| ID | Requirement |
|---|---|
| NF-OBS-01 | All services shall emit structured JSON logs to stdout with fields: `ts`, `level`, `service`, `logger`, `msg`. |
| NF-OBS-02 | Log records shall be compatible with standard aggregators (Loki, Datadog, CloudWatch). |

### 2.4 Correctness

| ID | Requirement |
|---|---|
| NF-COR-01 | Retrieved passages shall originate exclusively from the ingested document collection; vector-store internal or system documents shall be excluded from all query results. |
| NF-COR-02 | Answers shall be grounded in the retrieved passages; the LLM shall not be prompted to answer from training knowledge alone. |

### 2.5 Security

| ID | Requirement |
|---|---|
| NF-SEC-01 | API keys (`GOOGLE_API_KEY`, `OPENVIKING_API_KEY`) shall be supplied via environment variables and shall never be committed to version control. |
| NF-SEC-02 | The `.env` file shall be listed in `.gitignore`. |

### 2.6 Maintainability

| ID | Requirement |
|---|---|
| NF-MNT-01 | The API service shall maintain a unit + integration test suite with coverage of all Pydantic model validators and HTTP route behaviours. |
| NF-MNT-02 | The Marker service shall maintain a test suite covering route and model behaviours. |
| NF-MNT-03 | Shared constants (embedding prefixes, URI root, LLM endpoint) shall be defined in a single location and referenced from all consumers. |
| NF-MNT-04 | All Python code shall pass static type checking with `basedpyright` in standard mode. |

---

## 3. Constraints

| ID | Constraint |
|---|---|
| C-01 | The knowledge source is a single static PDF (`BCTN_MSB_2024.pdf`). Multi-document ingestion is out of scope. |
| C-02 | The embedding model is `qwen3-embedding` (4096-dimensional vectors). Changing the model requires a full re-ingestion. |
| C-03 | The system targets macOS / Apple Silicon for local development. GPU server deployment (NVIDIA CUDA) is documented but not yet implemented. |
| C-04 | All services run as Docker containers; the host requires Docker Desktop ≥ 4.30. |
| C-05 | Ollama must be running on the host before `make pre-convert` or `make up` (it is not containerised). |

---

## 4. Out of Scope

- Multi-user authentication and authorisation
- Multi-tenant or multi-document collections
- Reranking of retrieved passages
- Conversation history / multi-turn dialogue
- Active monitoring dashboards (Grafana, Prometheus)
- Full OpenTelemetry distributed tracing (tracked for a future iteration)
