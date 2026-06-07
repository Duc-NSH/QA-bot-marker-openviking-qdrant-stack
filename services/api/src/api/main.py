from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import api.logger as log_setup
from api.clients.marker_client import MarkerClient
from api.clients.ov_client import OVClient
from api.config import settings
from api.routers.query import router
from api.services.ingestion import run_ingestion

log_setup.setup(service="api", level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

_ingestion_done: bool = False
_ingestion_error: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _ingestion_done
    app.state.settings = settings
    app.state.ov_client = OVClient(
        base_url=settings.openviking_url,
        api_key=settings.openviking_api_key,
        account=settings.openviking_account,
        user=settings.openviking_user,
    )
    marker_client = MarkerClient(base_url=settings.marker_url)
    chunks_dir = Path(settings.processed_docs_path) / "chunks"
    state_path = Path(settings.processed_docs_path) / "ingest_state.json"

    logger.info("Starting up", extra={"pdf_path": settings.pdf_path, "chat_model": settings.chat_model})

    async def _ingest() -> None:
        global _ingestion_done, _ingestion_error
        try:
            await run_ingestion(
                pdf_path=Path(settings.pdf_path),
                state_path=state_path,
                chunks_dir=chunks_dir,
                marker_client=marker_client,
                ov_client=app.state.ov_client,
                qdrant_url=settings.qdrant_url,
            )
            _ingestion_done = True
            logger.info("Ingestion complete")
        except Exception:
            logger.exception("Ingestion failed")
            app.state.ingestion_error = "ingestion_failed"
            _ingestion_error = True

    asyncio.create_task(_ingest())
    yield
    logger.info("Shutting down")


app = FastAPI(title="Document QA API", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", extra={"path": str(request.url)})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict:
    if _ingestion_error:
        status = "error"
    elif _ingestion_done:
        status = "ready"
    else:
        status = "indexing"
    return {
        "status": status,
        "error": getattr(app.state, "ingestion_error", None),
    }
