from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncIterator

import httpx

from api.clients.ov_client import OVClient, OVClientError
from api.constants import DOC_PREFIX, GEMINI_BASE_URL
from api.models.document import ChunkIndex
from api.models.query import QueryRequest, QueryResponse, SourceChunk

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful assistant specialized in Vietnamese financial reports. "
    "Answer the user's question using only the provided context. "
    "Be concise, accurate, and cite specific figures when available. "
    "If the context does not contain the answer, say so clearly."
)


def build_sources(
    ov_resources: list[dict],
    *,
    chunk_index_path: Path,
    limit: int,
) -> list[SourceChunk]:
    """Convert OV find() results to SourceChunk list, deduped and enriched."""
    index = ChunkIndex.model_validate_json(chunk_index_path.read_text())
    chunks_dir = chunk_index_path.parent

    seen_uris: set[str] = set()
    sources: list[SourceChunk] = []

    for res in sorted(ov_resources, key=lambda r: r.get("score", 0.0), reverse=True):
        uri = res.get("uri", "")
        if uri in seen_uris:
            continue
        # Only accept resources from our bctn collection
        if not uri.startswith("viking://resources/bctn/"):
            continue
        seen_uris.add(uri)

        filename = uri.split("/")[-1]
        # Always use actual chunk content (Vietnamese). OV chunk abstracts are
        # auto-generated and may be in the wrong language (Gemini VLM issue).
        chunk_file = chunks_dir / filename
        raw_text = chunk_file.read_text(encoding="utf-8") if chunk_file.exists() else res.get("abstract", "")
        text = raw_text.removeprefix(DOC_PREFIX).strip()

        meta = index.entries.get(filename)
        sources.append(SourceChunk(
            uri=uri,
            text=text,
            score=res.get("score", 0.0),
            section_heading=meta.section_heading if meta else None,
            page_number=meta.page_number if meta else None,
        ))

        if len(sources) >= limit:
            break

    return sources


async def _openai_stream(
    question: str,
    context_chunks: list[str],
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> AsyncIterator[str]:
    """Stream tokens via the OpenAI-compatible chat completions endpoint."""
    context = "\n\n---\n\n".join(context_chunks)
    user_message = f"{question}\n\nContext:\n{context}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "stream": True,
        "temperature": 0.1,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=300.0, headers=headers) as client:
            async with client.stream("POST", f"{base_url}/chat/completions", json=payload) as resp:
                if not resp.is_success:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"LLM endpoint returned HTTP {resp.status_code}: {body[:200]}"
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload_str = line[len("data: "):]
                    if payload_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    token = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if token:
                        yield token
    except httpx.TimeoutException:
        raise TimeoutError("LLM request timed out after 120s")


async def stream_answer(
    *,
    request: QueryRequest,
    ov_client: OVClient,
    ollama_base_url: str,
    chat_model: str,
    chunk_index_path: Path,
    google_api_key: str | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Yield (event_type, data) tuples: ('token', text) and ('done', json)."""
    logger.info("Query received", extra={"question": request.question, "limit": request.limit})

    yield "status", "searching"
    try:
        ov_results = await ov_client.find(request.question, limit=request.limit * 3)
    except OVClientError as exc:
        logger.error("OV search failed", extra={"error": str(exc)})
        raise

    sources = build_sources(ov_results, chunk_index_path=chunk_index_path, limit=request.limit)
    context_chunks = [s.text for s in sources if s.text]

    logger.info(
        "Context built",
        extra={"source_count": len(sources), "context_chunks": len(context_chunks)},
    )

    if not context_chunks:
        logger.warning("No context chunks found for query", extra={"question": request.question})

    yield "status", "generating"
    if google_api_key:
        stream_fn = _openai_stream(
            request.question, context_chunks,
            base_url=GEMINI_BASE_URL, api_key=google_api_key, model=chat_model,
        )
    else:
        stream_fn = _openai_stream(
            request.question, context_chunks,
            base_url=f"{ollama_base_url}/v1", api_key="ollama", model=chat_model,
        )

    full_answer = ""
    async for token in stream_fn:
        full_answer += token
        yield "token", token

    logger.info("Answer streamed", extra={"answer_len": len(full_answer), "sources": len(sources)})
    yield "done", QueryResponse(answer=full_answer, sources=sources).model_dump_json()
