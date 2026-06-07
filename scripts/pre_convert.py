#!/usr/bin/env python3
"""Pre-convert PDF on the host (full RAM + GPU) and populate the Docker volume.

Usage:
    uv run --project services/marker python scripts/pre_convert.py

GOOGLE_API_KEY / OLLAMA_BASE_URL / OLLAMA_VLM_MODEL are read from .env in the
project root (or from the environment). Output is written to data/chunks/ and
then docker-copied into the ait-homework_processed_docs volume.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

_ROOT = Path(__file__).parent.parent
PDF_PATH = Path(os.environ.get("MARKER_PDF_PATH", str(_ROOT / "BCTN_MSB_2024_p1-20.pdf")))
OUT_DIR = _ROOT / "data" / "chunks"
DOC_PREFIX = "Represent this financial document passage for retrieval: "

_OV_CONF_TEMPLATE = _ROOT / "openviking" / "ov.conf.template"
_OV_CONF_OUT = _ROOT / "openviking" / "ov.conf"

# Pages are 0-indexed; set MARKER_PAGE_RANGE to override (e.g. "0-266" for full PDF)
PAGE_RANGE = os.environ.get("MARKER_PAGE_RANGE", "0-19")

_PAGE_SEP = "-" * 48


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------
def _load_dotenv() -> None:
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_VLM_MODEL = os.environ.get("OLLAMA_VLM_MODEL", "qwen3:14b")


# ---------------------------------------------------------------------------
# ov.conf generation
# ---------------------------------------------------------------------------
def generate_ov_conf() -> None:
    """Build openviking/ov.conf from template, selecting VLM based on env."""
    if not _OV_CONF_TEMPLATE.exists():
        print(f"WARNING: {_OV_CONF_TEMPLATE} not found — skipping ov.conf generation")
        return

    conf = json.loads(_OV_CONF_TEMPLATE.read_text())

    if GOOGLE_API_KEY:
        vlm = {
            "provider": "openai",
            "model": "gemini-2.5-flash",
            "api_key": GOOGLE_API_KEY,
            "api_base": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "temperature": 0.0,
            "max_retries": 2,
        }
        print(f"VLM: Gemini 2.5-flash (Google API)")
    else:
        vlm = {
            "provider": "openai",
            "model": OLLAMA_VLM_MODEL,
            "api_key": "ollama",
            "api_base": f"{OLLAMA_BASE_URL}/v1/",
            "temperature": 0.0,
            "max_retries": 2,
        }
        print(f"VLM: Ollama ({OLLAMA_VLM_MODEL} at {OLLAMA_BASE_URL})")

    conf["vlm"] = vlm
    _OV_CONF_OUT.write_text(json.dumps(conf, indent=4, ensure_ascii=False))
    print(f"Generated {_OV_CONF_OUT}")


# ---------------------------------------------------------------------------
# Chunk splitting
# ---------------------------------------------------------------------------
def _make_chunk(text: str, section: str | None, page: int) -> dict:
    stripped = text.strip()
    if re.search(r"^\|[-| :]+\|", stripped, re.MULTILINE):
        content_type: Literal["text", "table", "figure_caption"] = "table"
    elif stripped.lower().startswith(("figure", "hình", "biểu đồ")):
        content_type = "figure_caption"
    else:
        content_type = "text"
    return {"text": stripped, "section_heading": section, "page_number": page, "content_type": content_type}


def _split_into_chunks(rendered: Any) -> list[dict]:
    markdown = rendered.markdown if hasattr(rendered, "markdown") else str(rendered)
    page_texts = re.split(r"\n*" + re.escape(_PAGE_SEP) + r"\n*", markdown)

    chunks: list[dict] = []
    current_section: str | None = None

    for page_num, page_text in enumerate(page_texts, start=1):
        if not page_text.strip():
            continue
        parts = re.split(r"(?m)^(#{1,3} .+)$", page_text)
        buffer = ""
        for part in parts:
            heading_match = re.match(r"^#{1,3} (.+)$", part)
            if heading_match:
                if buffer.strip():
                    chunks.append(_make_chunk(buffer, current_section, page_num))
                    buffer = ""
                current_section = heading_match.group(1).strip()
            else:
                buffer += part
        if buffer.strip():
            chunks.append(_make_chunk(buffer, current_section, page_num))

    return chunks


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------
def run_conversion() -> list[dict]:
    if not PDF_PATH.exists():
        print(f"ERROR: {PDF_PATH} not found.")
        sys.exit(1)

    print("Loading marker models (this may take a while)...")
    from marker.models import create_model_dict
    models = create_model_dict()

    start, end = (int(x) for x in PAGE_RANGE.split("-"))
    print(f"Converting {PDF_PATH.name} pages {PAGE_RANGE}...")
    from marker.converters.pdf import PdfConverter
    converter = PdfConverter(artifact_dict=models, config={"page_range": list(range(start, end + 1))})
    rendered = converter(str(PDF_PATH))
    chunks = _split_into_chunks(rendered)
    print(f"Extracted {len(chunks)} chunks from pages {PAGE_RANGE}")
    return chunks


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def write_chunks(chunks: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index_entries: dict[str, dict] = {}

    for i, chunk in enumerate(chunks):
        filename = f"chunk_{i:04d}_p{chunk['page_number']:03d}.md"
        (OUT_DIR / filename).write_text(DOC_PREFIX + chunk["text"], encoding="utf-8")
        index_entries[filename] = {
            "section_heading": chunk["section_heading"],
            "page_number": chunk["page_number"],
            "content_type": chunk["content_type"],
        }

    (OUT_DIR / "chunk_index.json").write_text(json.dumps({"entries": index_entries}), encoding="utf-8")
    print(f"Written {len(chunks)} chunks to {OUT_DIR}")


def copy_to_volume() -> None:
    print("Copying chunks into ait-homework_processed_docs volume...")
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{OUT_DIR.parent}:/src",
            "-v", "ait-homework_processed_docs:/dst",
            "alpine",
            "sh", "-c",
            "mkdir -p /dst/chunks && cp /src/chunks/* /dst/chunks/ && rm -f /dst/ingest_state.json",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("ERROR:", result.stderr)
        sys.exit(1)
    print("Done — chunks in volume, ingest_state.json cleared")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    generate_ov_conf()
    chunks = run_conversion()
    write_chunks(chunks)
    copy_to_volume()
    print()
    print("Next steps:")
    print("  make clean && make up   # wipe old OV data, start fresh")
