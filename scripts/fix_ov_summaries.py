"""fix_ov_summaries.py — translate OV L0/L1 summaries to English in-place.

OpenViking auto-generates L0 (.abstract) and L1 (.overview) directory summaries
using the configured VLM. When the VLM sees Vietnamese text (Latin script with
diacritics) it may generate summaries in Portuguese instead of English. This
script reads the existing summaries, translates them to English via the LLM, and
writes them back via docker cp (the content/write API rejects derived semantic
files) — no re-ingestion required.

Usage (stack must be running):
    uv run python scripts/fix_ov_summaries.py [--dry-run]

Requirements: Docker must be accessible from the host (docker cp).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Config (read from .env if present)
# ---------------------------------------------------------------------------

_ENV = Path(__file__).parent.parent / ".env"
if _ENV.exists():
    for line in _ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

OV_URL          = os.environ.get("OPENVIKING_URL", "http://openviking.localhost")
OV_KEY          = os.environ.get("OPENVIKING_API_KEY", "ait-dev")
OV_ACCOUNT      = os.environ.get("OPENVIKING_ACCOUNT", "default")
OV_USER         = os.environ.get("OPENVIKING_USER", "api")
GOOGLE_API_KEY  = os.environ.get("GOOGLE_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
CHAT_MODEL      = os.environ.get("CHAT_MODEL", "gemini-2.5-flash")
GEMINI_BASE     = "https://generativelanguage.googleapis.com/v1beta/openai"

# Docker container name for the OV service (used for docker cp writes).
OV_CONTAINER    = os.environ.get("OPENVIKING_CONTAINER", "ait-homework-openviking-1")
# Internal workspace path inside the container.
OV_WORKSPACE    = os.environ.get("OPENVIKING_WORKSPACE", "/app/.openviking/data")

# Directories to fix — extend this list if you add more collections.
TARGET_DIRS = ["viking://resources/bctn/"]

OV_HEADERS = {
    "X-API-Key": OV_KEY,
    "X-OpenViking-Account": OV_ACCOUNT,
    "X-OpenViking-User": OV_USER,
}

# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def _llm_translate(text: str) -> str:
    """Translate *text* to English using the configured LLM (with retry on 429)."""
    import time

    system = (
        "You are a professional translator. "
        "Translate the following text to English. "
        "Preserve all Markdown formatting, headings, bullet points, and file name references exactly. "
        "Output only the translated text — no preamble, no explanation."
    )
    payload = {
        "model": CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "stream": False,
    }
    if GOOGLE_API_KEY:
        base_url = GEMINI_BASE
        api_key = GOOGLE_API_KEY
    else:
        base_url = f"{OLLAMA_BASE_URL}/v1"
        api_key = "ollama"

    for attempt in range(4):
        resp = httpx.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=120,
        )
        if resp.status_code == 429:
            wait = 15 * (attempt + 1)
            print(f"    429 rate limit — retrying in {wait}s…")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    raise RuntimeError("LLM translation failed after retries (persistent 429)")

# ---------------------------------------------------------------------------
# OV helpers
# ---------------------------------------------------------------------------

def _ov_read(endpoint: str, uri: str) -> str | None:
    """Read L0 abstract or L1 overview for *uri*. Returns None if not found."""
    resp = httpx.get(
        f"{OV_URL}/api/v1/content/{endpoint}",
        params={"uri": uri},
        headers=OV_HEADERS,
        timeout=30,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    return data.get("result") or None


def _uri_to_container_path(dir_uri: str, file_name: str) -> str:
    """Convert a viking:// directory URI to the absolute path inside the OV container.

    E.g. "viking://resources/bctn/" + ".abstract.md"
    → "/app/.openviking/data/viking/default/resources/bctn/.abstract.md"
    """
    # Strip scheme: viking://resources/bctn/ → resources/bctn
    without_scheme = dir_uri.removeprefix("viking://").rstrip("/")
    return f"{OV_WORKSPACE}/viking/{OV_ACCOUNT}/{without_scheme}/{file_name}"


def _docker_write(dir_uri: str, file_name: str, content: str, dry_run: bool) -> None:
    """Write *content* to the OV container file via docker cp.

    OV treats .abstract.md / .overview.md as derived semantic files and blocks
    writes via the content/write API endpoint, so we copy files directly.
    """
    container_path = _uri_to_container_path(dir_uri, file_name)
    if dry_run:
        print(f"    [DRY RUN] would docker cp {len(content)} chars → {OV_CONTAINER}:{container_path}")
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        subprocess.run(
            ["docker", "cp", tmp_path, f"{OV_CONTAINER}:{container_path}"],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"    docker cp → {container_path} ({len(content)} chars)")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"docker cp failed: {exc.stderr}") from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fix_dir(dir_uri: str, dry_run: bool) -> None:
    print(f"\n{'='*60}")
    print(f"Directory: {dir_uri}")

    for layer, endpoint, file_name in [
        ("L0 abstract", "abstract", ".abstract.md"),
        ("L1 overview", "overview", ".overview.md"),
    ]:
        print(f"\n  {layer}:")
        original = _ov_read(endpoint, dir_uri)
        if not original:
            print(f"    (empty or not found — skipping)")
            continue

        first_line = original.splitlines()[0][:80]
        print(f"    current: {first_line!r}…")

        translated = _llm_translate(original)
        first_line_t = translated.splitlines()[0][:80]
        print(f"    translated: {first_line_t!r}…")

        # OV blocks writing derived semantic files via content/write API;
        # use docker cp to write directly into the container filesystem.
        _docker_write(dir_uri, file_name, translated, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print translations without writing back to OV")
    args = parser.parse_args()

    if not GOOGLE_API_KEY and CHAT_MODEL.startswith("gemini"):
        print("ERROR: GOOGLE_API_KEY not set and CHAT_MODEL is Gemini.", file=sys.stderr)
        sys.exit(1)

    for uri in TARGET_DIRS:
        fix_dir(uri, dry_run=args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
