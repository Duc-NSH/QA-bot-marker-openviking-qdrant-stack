#!/usr/bin/env python3
"""
Full end-to-end test runner for the Document QA pipeline.

Orchestrates: clean → pre-convert → services up → ingest wait → queries → report.
Writes docs/test-report.md when complete.

Usage:
    uv run --project services/marker python scripts/run_full_test.py 2>&1 | tee /tmp/full_test.log
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
REPORT_PATH = _ROOT / "docs" / "test-report.md"

TEST_QUESTIONS = [
    "Tổng tài sản của MSB năm 2024 là bao nhiêu?",
    "Lợi nhuận trước thuế của MSB năm 2024 là bao nhiêu?",
    "Vốn chủ sở hữu của MSB năm 2024 là bao nhiêu?",
    "MSB có bao nhiêu chi nhánh và phòng giao dịch?",
    "Tỷ lệ nợ xấu (NPL) của MSB năm 2024 là bao nhiêu?",
]

API_URL = "http://api.localhost"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ts() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _elapsed(start: float) -> str:
    s = int(time.time() - start)
    return f"{s // 60}m {s % 60}s"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"\n[{_ts()}] $ {' '.join(cmd)}")
    return subprocess.run(cmd, **kwargs)


def _wait_health(timeout: int = 600, min_vectors: int = 0) -> tuple[bool, float]:
    """Poll /health until status=ready AND Qdrant has min_vectors. Returns (ok, wait_seconds)."""
    deadline = time.time() + timeout
    start = time.time()
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{API_URL}/health", timeout=5) as r:
                data = json.loads(r.read())
                status = data.get("status")
                if status == "ready":
                    if min_vectors == 0:
                        return True, time.time() - start
                    vc = _qdrant_count()
                    if vc >= min_vectors:
                        return True, time.time() - start
                    print(f"  [health] API ready but {vc}/{min_vectors} vectors indexed — waiting…")
                else:
                    print(f"  [health] status={status} — waiting…")
        except Exception:
            pass
        time.sleep(10)
    return False, time.time() - start


def _query(question: str, limit: int = 5) -> dict:
    """Fire a query, consume SSE stream, return {answer, sources, elapsed_s, error}."""
    payload = json.dumps({"question": question, "limit": limit}).encode()
    req = urllib.request.Request(
        f"{API_URL}/query",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if "answer" in obj:
                    return {
                        "answer": obj["answer"],
                        "sources": obj.get("sources", []),
                        "elapsed_s": round(time.time() - t0, 1),
                        "error": None,
                    }
                if obj.get("message"):  # error event
                    return {"answer": "", "sources": [], "elapsed_s": round(time.time() - t0, 1),
                            "error": obj["message"]}
    except Exception as exc:
        return {"answer": "", "sources": [], "elapsed_s": round(time.time() - t0, 1), "error": str(exc)}
    return {"answer": "", "sources": [], "elapsed_s": round(time.time() - t0, 1), "error": "no done event"}


def _qdrant_count() -> int:
    try:
        with urllib.request.urlopen("http://qdrant.localhost/collections", timeout=5) as r:
            cols = json.loads(r.read()).get("result", {}).get("collections", [])
            for col in cols:
                name = col.get("name", "")
                with urllib.request.urlopen(f"http://qdrant.localhost/collections/{name}", timeout=5) as r2:
                    info = json.loads(r2.read())
                    return int(info.get("result", {}).get("points_count", 0))
    except Exception:
        pass
    return -1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    run_start = time.time()
    phases: list[dict] = []
    errors: list[str] = []

    pdf_path = os.environ.get("MARKER_PDF_PATH", str(_ROOT / "BCTN_MSB_2024.pdf"))
    page_range = os.environ.get("MARKER_PAGE_RANGE", "0-266")

    print(f"[{_ts()}] === FULL END-TO-END TEST ===")
    print(f"PDF: {pdf_path}  pages: {page_range}")

    # ── Phase 1: clean ────────────────────────────────────────────────────
    p_start = time.time()
    print(f"\n[{_ts()}] Phase 1: Clean (docker compose down -v)")
    r = _run(["docker", "compose", "down", "-v"], capture_output=True, text=True, cwd=_ROOT)
    if r.returncode != 0:
        errors.append(f"clean: {r.stderr[:200]}")
    phases.append({"name": "Clean volumes", "elapsed": _elapsed(p_start), "ok": r.returncode == 0})

    # ── Phase 2: pre-convert ───────────────────────────────────────────────
    p_start = time.time()
    print(f"\n[{_ts()}] Phase 2: Pre-convert PDF ({page_range} pages)")
    env = {**os.environ, "MARKER_PDF_PATH": pdf_path, "MARKER_PAGE_RANGE": page_range}
    r = _run(
        ["uv", "run", "--project", "services/marker", "python", "scripts/pre_convert.py"],
        env=env, cwd=_ROOT,
    )
    elapsed_convert = _elapsed(p_start)
    ok_convert = r.returncode == 0

    # Count chunks written
    chunk_count = len(list((_ROOT / "data" / "chunks").glob("chunk_*.md")))
    phases.append({
        "name": f"Pre-convert ({page_range})",
        "elapsed": elapsed_convert,
        "ok": ok_convert,
        "detail": f"{chunk_count} chunks extracted",
    })
    if not ok_convert:
        errors.append(f"pre-convert failed (exit {r.returncode})")
        print("ERROR: pre-convert failed. Aborting.")
        _write_report(phases, errors, [], run_start, pdf_path, page_range, chunk_count, -1)
        sys.exit(1)
    print(f"  Chunks: {chunk_count}")

    # ── Phase 3: services up ───────────────────────────────────────────────
    p_start = time.time()
    print(f"\n[{_ts()}] Phase 3: Build and start services")
    r = _run(["docker", "compose", "build"], capture_output=True, text=True, cwd=_ROOT)
    if r.returncode != 0:
        errors.append(f"compose build: {r.stderr[:200]}")
    r = _run(["docker", "compose", "up", "-d"], capture_output=True, text=True, cwd=_ROOT)
    if r.returncode != 0:
        errors.append(f"compose up: {r.stderr[:200]}")
    phases.append({"name": "Services up (with build)", "elapsed": _elapsed(p_start), "ok": r.returncode == 0})

    # ── Phase 4: wait for API ready ────────────────────────────────────────
    p_start = time.time()
    print(f"\n[{_ts()}] Phase 4: Wait for API ready (ingestion + embeddings)")
    ready, wait_s = _wait_health(timeout=3600, min_vectors=chunk_count)  # wait for all vectors
    vector_count = _qdrant_count()
    phases.append({
        "name": "API ready / ingestion",
        "elapsed": f"{int(wait_s // 60)}m {int(wait_s % 60)}s",
        "ok": ready,
        "detail": f"{vector_count} vectors in qdrant",
    })
    if not ready:
        errors.append("API did not reach ready within timeout")

    # ── Phase 5: smoke queries ─────────────────────────────────────────────
    p_start = time.time()
    print(f"\n[{_ts()}] Phase 5: Running {len(TEST_QUESTIONS)} test queries")
    results = []
    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"  [{i}/{len(TEST_QUESTIONS)}] {q}")
        res = _query(q)
        results.append({"question": q, **res})
        status = "OK" if res["answer"] and not res["error"] else "FAIL"
        print(f"    {status} ({res['elapsed_s']}s) → {res['answer'][:100]}…" if res["answer"] else f"    {status} — {res['error']}")
        if res["error"]:
            errors.append(f"query '{q[:40]}': {res['error']}")
    phases.append({"name": f"Smoke queries ({len(TEST_QUESTIONS)})", "elapsed": _elapsed(p_start), "ok": not any(r["error"] for r in results)})

    # ── Write report ───────────────────────────────────────────────────────
    _write_report(phases, errors, results, run_start, pdf_path, page_range, chunk_count, vector_count)
    print(f"\n[{_ts()}] Test complete — report written to {REPORT_PATH}")
    print(f"Total elapsed: {_elapsed(run_start)}")


def _write_report(
    phases: list[dict],
    errors: list[str],
    results: list[dict],
    run_start: float,
    pdf_path: str,
    page_range: str,
    chunk_count: int,
    vector_count: int,
) -> None:
    total = _elapsed(run_start)
    date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    overall_ok = not errors

    lines = [
        f"# Full End-to-End Test Report",
        f"",
        f"**Date:** {date}  ",
        f"**PDF:** `{Path(pdf_path).name}` ({page_range} pages)  ",
        f"**Chunks extracted:** {chunk_count}  ",
        f"**Vectors in Qdrant:** {vector_count}  ",
        f"**Total elapsed:** {total}  ",
        f"**Result:** {'✅ PASS' if overall_ok else '❌ FAIL'}",
        f"",
        f"---",
        f"",
        f"## Phase Timings",
        f"",
        f"| Phase | Elapsed | Status | Notes |",
        f"|---|---|---|---|",
    ]
    for p in phases:
        icon = "✅" if p["ok"] else "❌"
        detail = p.get("detail", "")
        lines.append(f"| {p['name']} | {p['elapsed']} | {icon} | {detail} |")

    lines += [
        f"",
        f"## Bottlenecks",
        f"",
    ]
    # Identify slowest phase
    for p in phases:
        mins = int(p["elapsed"].split("m")[0])
        if mins >= 5:
            lines.append(f"- **{p['name']}** took {p['elapsed']} — "
                         + ("Marker PDF OCR runs locally on CPU/GPU; primary bottleneck for large PDFs."
                            if "convert" in p["name"].lower()
                            else "qwen3-embedding processes one call at a time; scales linearly with chunk count."
                            if "ingest" in p["name"].lower() or "ready" in p["name"].lower()
                            else ""))

    lines += [
        f"",
        f"## Errors",
        f"",
    ]
    if errors:
        for e in errors:
            lines.append(f"- {e}")
    else:
        lines.append("None.")

    lines += [
        f"",
        f"## Query Results",
        f"",
    ]
    for r in results:
        icon = "✅" if r["answer"] and not r["error"] else "❌"
        lines.append(f"### {icon} {r['question']}")
        lines.append(f"")
        if r["answer"]:
            lines.append(f"**Answer:** {r['answer']}")
            lines.append(f"")
            lines.append(f"**Elapsed:** {r['elapsed_s']}s | **Sources:** {len(r['sources'])}")
            if r["sources"]:
                lines.append(f"")
                lines.append(f"| Score | Page | URI |")
                lines.append(f"|---|---|---|")
                for s in r["sources"]:
                    lines.append(f"| {s['score']:.3f} | {s.get('page_number','?')} | `{s['uri']}` |")
        else:
            lines.append(f"**Error:** {r.get('error', 'no answer')}")
        lines.append(f"")

    lines += [
        f"---",
        f"",
        f"## Notes for Production",
        f"",
        f"- **GPU server (NVIDIA):** See `docs/deployment.md` — run Marker in a CUDA container to",
        f"  eliminate the host pre-convert step and reduce OCR time by 5–10×.",
        f"- **Embedding throughput:** `qwen3-embedding` processes one request at a time via Ollama.",
        f"  Replace with a batched embedding server (e.g. TEI, vLLM) for 10–50× speedup.",
        f"- **Full OTEL tracing:** See `docs/deployment.md` for the collector stack.",
        f"- **Gemini LLM in Marker:** `use_llm=True` with `GoogleGeminiService` improves OCR",
        f"  quality on scanned Vietnamese pages but adds ~1–2s per page; consider enabling for",
        f"  production once cost is acceptable.",
    ]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
