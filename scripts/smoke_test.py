#!/usr/bin/env python3
"""Smoke test: fire a query against the running stack and print the answer."""
from __future__ import annotations

import json
import sys
import urllib.request

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "Tổng tài sản của MSB năm 2024 là bao nhiêu?"
URL = "http://api.localhost/query"


def main() -> None:
    payload = json.dumps({"question": QUESTION, "limit": 5}).encode()
    req = urllib.request.Request(URL, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            event_type = None
            for raw_line in resp:
                line = raw_line.decode().strip()
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                if event_type == "token":
                    print(data, end="", flush=True)
                elif event_type == "done":
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    print(f"\n\nAnswer: {obj['answer']}\n")
                    for s in obj.get("sources", []):
                        print(f"  [{s['score']:.3f}] p{s['page_number']} {s['uri']}")
                    return
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
