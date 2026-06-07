from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

import marker_svc.logger as log_setup
from marker_svc.models import ConvertRequest, ConvertResponse, PageChunk

log_setup.setup(service="marker", level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_models: dict | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _models
    logger.info("Loading marker models")
    from marker.models import create_model_dict
    _models = create_model_dict()
    logger.info("Marker models loaded")
    yield
    _models = None


app = FastAPI(title="Marker Service", lifespan=lifespan)


@app.exception_handler(Exception)
async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health(response: Response) -> dict[str, str]:
    if _models is None:
        response.status_code = 503
        return {"status": "loading"}
    return {"status": "ok"}


@app.post("/convert", response_model=ConvertResponse)
def convert(req: ConvertRequest) -> ConvertResponse:
    if _models is None:
        raise HTTPException(status_code=503, detail="Models not ready")
    path = Path(req.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")
    logger.info("Starting conversion", extra={"file": req.file_path})
    chunks = _run_marker(str(path))
    logger.info("Conversion complete", extra={"chunk_count": len(chunks)})
    return ConvertResponse(chunks=chunks)


def _run_marker(file_path: str) -> list[PageChunk]:
    from marker.converters.pdf import PdfConverter

    config: dict[str, Any] = {}
    if page_range := os.environ.get("MARKER_PAGE_RANGE"):
        start, end = (int(x) for x in page_range.split("-"))
        config["page_range"] = list(range(start, end + 1))
    converter = PdfConverter(artifact_dict=_models, config=config or None)
    rendered = converter(file_path)
    return _split_into_chunks(rendered)


_PAGE_SEP = "-" * 48


def _split_into_chunks(rendered: Any) -> list[PageChunk]:
    markdown = rendered.markdown if hasattr(rendered, "markdown") else str(rendered)
    page_texts = re.split(r"\n*" + re.escape(_PAGE_SEP) + r"\n*", markdown)

    chunks: list[PageChunk] = []
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


def _make_chunk(text: str, section: str | None, page: int) -> PageChunk:
    stripped = text.strip()
    if re.search(r"^\|[-| :]+\|", stripped, re.MULTILINE):
        content_type: Literal["text", "table", "figure_caption"] = "table"
    elif stripped.lower().startswith(("figure", "hình", "biểu đồ")):
        content_type = "figure_caption"
    else:
        content_type = "text"
    return PageChunk(text=stripped, section_heading=section, page_number=page, content_type=content_type)
