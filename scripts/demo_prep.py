"""demo_prep.py — pre-run demo questions against the live API and save results.

Usage:
    uv run python scripts/demo_prep.py [--api http://api.localhost]

Writes frontend/static/demo_data.json.
The stack must be running and /health must return {"status": "ready"}.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

QUESTIONS = [
    "Tổng tài sản của MSB năm 2024 là bao nhiêu?",
    "Lợi nhuận trước thuế của MSB năm 2024 là bao nhiêu?",
    "Vốn chủ sở hữu của MSB năm 2024 là bao nhiêu?",
    "Tỷ lệ nợ xấu (NPL) của MSB năm 2024 là bao nhiêu?",
    "MSB có bao nhiêu chi nhánh và phòng giao dịch năm 2024?",
]

OUTPUT = Path(__file__).parent.parent / "frontend" / "static" / "demo_data.json"


def wait_for_ready(api: str, timeout: int = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{api}/health", timeout=5)
            if resp.json().get("status") == "ready":
                print("API ready.")
                return
        except Exception:
            pass
        print("Waiting for API…")
        time.sleep(3)
    print("ERROR: API not ready after timeout.", file=sys.stderr)
    sys.exit(1)


def run_query(api: str, question: str) -> dict:
    """Stream /query and return {question, answer, sources, elapsed_s}."""
    print(f"  Q: {question}")
    t0 = time.time()
    answer = ""
    sources = []

    with httpx.Client(timeout=300) as client:
        with client.stream(
            "POST",
            f"{api}/query",
            json={"question": question, "limit": 5},
            headers={"Accept": "text/event-stream"},
        ) as resp:
            resp.raise_for_status()
            event_type = "message"
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if event_type == "token":
                        answer += data
                    elif event_type == "done":
                        payload = json.loads(data)
                        answer = payload.get("answer", answer)
                        sources = payload.get("sources", [])
                    event_type = "message"

    elapsed = round(time.time() - t0, 1)
    print(f"     → {elapsed}s, {len(sources)} sources")
    return {"question": question, "answer": answer, "sources": sources, "elapsed_s": elapsed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://api.localhost")
    args = parser.parse_args()

    print(f"Target: {args.api}")
    wait_for_ready(args.api)

    results = []
    for q in QUESTIONS:
        results.append(run_query(args.api, q))

    OUTPUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved {len(results)} results to {OUTPUT}")


if __name__ == "__main__":
    main()
