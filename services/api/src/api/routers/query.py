from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from api.clients.marker_client import MarkerError
from api.clients.ov_client import OVClientError
from api.models.query import QueryRequest
from api.services.qa import stream_answer

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query")
async def query(req: QueryRequest, request: Request) -> EventSourceResponse:
    ov_client = request.app.state.ov_client
    settings = request.app.state.settings
    chunk_index_path = Path(settings.processed_docs_path) / "chunks" / "chunk_index.json"

    if not chunk_index_path.exists():
        raise HTTPException(status_code=503, detail="Index not ready — ingestion in progress")

    async def event_generator():
        try:
            async for event_type, data in stream_answer(
                request=req,
                ov_client=ov_client,
                ollama_base_url=settings.ollama_base_url,
                chat_model=settings.chat_model,
                chunk_index_path=chunk_index_path,
                google_api_key=settings.google_api_key,
            ):
                yield {"event": event_type, "data": data}
        except OVClientError as exc:
            logger.error("OV error during query", extra={"error": str(exc)})
            yield {"event": "error", "data": json.dumps({"message": "Search service error", "detail": str(exc)})}
        except MarkerError as exc:
            logger.error("Marker error during query", extra={"error": str(exc)})
            yield {"event": "error", "data": json.dumps({"message": "Conversion service error", "detail": str(exc)})}
        except TimeoutError as exc:
            logger.error("Timeout during query", extra={"error": str(exc)})
            yield {"event": "error", "data": json.dumps({"message": "Request timed out", "detail": str(exc)})}
        except Exception as exc:
            logger.exception("Unexpected error during query")
            yield {"event": "error", "data": json.dumps({"message": "Internal server error", "detail": repr(exc)})}

    return EventSourceResponse(event_generator())
