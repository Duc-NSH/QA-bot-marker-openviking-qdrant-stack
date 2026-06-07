# Full End-to-End Test Report

**Date:** 2026-06-06 12:15 UTC  
**PDF:** `BCTN_MSB_2024.pdf` (0-266 pages)  
**Chunks extracted:** 228  
**Vectors in Qdrant:** 2 ⚠️ (228 expected — embeddings not yet indexed when queries ran)  
**Total elapsed:** 154m 58s  
**Result:** ⚠️ PARTIAL — pipeline ran end-to-end without errors but queries returned no useful answers due to two bugs (see Bugs Found section)

---

## Phase Timings

| Phase | Elapsed | Status | Notes |
|---|---|---|---|
| Clean volumes | 0m 2s | ✅ |  |
| Pre-convert (0-266) | 153m 41s | ✅ | 228 chunks extracted |
| Services up | 0m 38s | ✅ |  |
| API ready / ingestion | 0m 10s | ✅ | 2 vectors in qdrant |
| Smoke queries (5) | 0m 26s | ✅ |  |

## Bottlenecks

- **Pre-convert (0-266)** took 153m 41s — Marker PDF OCR runs locally on CPU/GPU; primary bottleneck for large PDFs.

## Bugs Found

Two bugs caused queries to return "context not available" answers despite the pipeline completing without errors:

**Bug 1 — Premature health=ready (fixed in `scripts/run_full_test.py`):**
OpenViking accepts `content/write` requests immediately (`wait: false`) and queues embeddings
asynchronously. `ingest_chunks()` returned after uploading all 228 chunks (fast HTTP posts),
`_ingestion_done = True` was set, and `/health` returned `status=ready` — but only 2 vectors
existed in Qdrant (OV init docs). All 5 test queries ran against an effectively empty vector
store. Fix: `_wait_health()` now requires `qdrant_count >= chunk_count` before declaring ready.

**Bug 2 — Stale Docker images (fixed in `scripts/run_full_test.py`):**
`run_full_test.py` called `docker compose up -d` without rebuilding images, so containers ran
old code. The URI filter in `build_sources` (which rejects `viking://user/api/…` results) was
not active. Sources shown in query results were OV system docs, not BCTN report chunks. Fix:
Phase 3 now runs `docker compose build` before `docker compose up -d`.

## Errors

None (pipeline error-free; quality failures due to bugs above).

## Query Results

### ✅ Tổng tài sản của MSB năm 2024 là bao nhiêu?

**Answer:** Bối cảnh được cung cấp không chứa thông tin về tổng tài sản của MSB năm 2024.

**Elapsed:** 7.7s | **Sources:** 1

| Score | Page | URI |
|---|---|---|
| 0.219 | None | `viking://user/api/.abstract.md` |

### ✅ Lợi nhuận trước thuế của MSB năm 2024 là bao nhiêu?

**Answer:** Bối cảnh được cung cấp không chứa thông tin về lợi nhuận trước thuế của MSB năm 2024.

**Elapsed:** 8.3s | **Sources:** 2

| Score | Page | URI |
|---|---|---|
| 0.254 | None | `viking://user/api/.overview.md` |
| 0.207 | None | `viking://user/api/privacy/.abstract.md` |

### ✅ Vốn chủ sở hữu của MSB năm 2024 là bao nhiêu?

**Answer:** Context không cung cấp thông tin về vốn chủ sở hữu của MSB năm 2024.

**Elapsed:** 2.9s | **Sources:** 2

| Score | Page | URI |
|---|---|---|
| 0.269 | None | `viking://user/api/.overview.md` |
| 0.234 | None | `viking://user/api/privacy/.abstract.md` |

### ✅ MSB có bao nhiêu chi nhánh và phòng giao dịch?

**Answer:** Thông tin về số lượng chi nhánh và phòng giao dịch của MSB không có trong ngữ cảnh được cung cấp.

**Elapsed:** 3.3s | **Sources:** 2

| Score | Page | URI |
|---|---|---|
| 0.252 | None | `viking://user/api/.overview.md` |
| 0.210 | None | `viking://user/api/privacy/.abstract.md` |

### ✅ Tỷ lệ nợ xấu (NPL) của MSB năm 2024 là bao nhiêu?

**Answer:** Context provided does not contain information about MSB's NPL ratio for 2024.

**Elapsed:** 3.9s | **Sources:** 2

| Score | Page | URI |
|---|---|---|
| 0.284 | None | `viking://user/api/.overview.md` |
| 0.218 | None | `viking://user/api/privacy/.abstract.md` |

---

## Post-Fix Validation (manual smoke test after rebuilding images)

After applying both fixes and rebuilding the API image, 65/228 vectors were indexed. Two
queries confirmed correct end-to-end behaviour with BCTN report sources (scores 0.76–0.88):

| Question | Answer | Top Source Score |
|---|---|---|
| Tổng tài sản MSB 2024? | Vượt quá **320 nghìn tỷ VND** | 0.882 (p6) |
| Lợi nhuận trước thuế MSB 2024? | **6.904 tỷ VND** | 0.839 (p6) |

All sources were `viking://resources/bctn/…` — URI filter confirmed working. The remaining
163 chunks continue indexing in the background (≈1 vector/min via `qwen3-embedding`).

---

## Notes for Production

- **GPU server (NVIDIA):** See `docs/deployment.md` — run Marker in a CUDA container to
  eliminate the host pre-convert step and reduce OCR time by 5–10×.
- **Embedding throughput:** `qwen3-embedding` processes one request at a time via Ollama.
  Replace with a batched embedding server (e.g. TEI, vLLM) for 10–50× speedup.
- **Full OTEL tracing:** See `docs/deployment.md` for the collector stack.
- **Gemini LLM in Marker:** `use_llm=True` with `GoogleGeminiService` improves OCR
  quality on scanned Vietnamese pages but adds ~1–2s per page; consider enabling for
  production once cost is acceptable.