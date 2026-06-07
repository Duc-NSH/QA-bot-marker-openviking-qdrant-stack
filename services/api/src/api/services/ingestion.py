from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from api.clients.marker_client import MarkerClient
from api.clients.ov_client import OVClient
from api.constants import DOC_PREFIX
from api.models.document import ChunkIndex, ChunkMeta, IngestState

logger = logging.getLogger(__name__)


def _pdf_hash(pdf_path: Path) -> str:
    """Return the first 16 hex chars of the SHA-256 digest of the PDF."""
    return hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]


async def _wait_for_vectors(
    qdrant_url: str,
    expected: int,
    timeout: int = 3600,
) -> None:
    """Poll Qdrant until the total indexed point count reaches *expected*.

    OpenViking queues embeddings asynchronously after content/write, so vectors
    are not immediately available. This ensures /health only reports ready once
    the full collection is searchable.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    async with httpx.AsyncClient(timeout=10.0) as client:
        while loop.time() < deadline:
            try:
                cols_resp = await client.get(f"{qdrant_url}/collections")
                collections = cols_resp.json().get("result", {}).get("collections", [])
                total = 0
                for col in collections:
                    name = col.get("name", "")
                    if name.startswith("__"):
                        continue  # skip OV internal meta collection
                    info_resp = await client.get(f"{qdrant_url}/collections/{name}")
                    total += info_resp.json().get("result", {}).get("points_count", 0)
                if total >= expected:
                    logger.info("Vector indexing complete", extra={"indexed": total, "expected": expected})
                    return
                logger.info("Waiting for vectors", extra={"indexed": total, "expected": expected})
            except Exception as exc:
                logger.debug("Qdrant poll error", extra={"error": str(exc)})
            await asyncio.sleep(10)
    logger.warning("Timed out waiting for vectors", extra={"expected": expected})


async def run_ingestion(
    *,
    pdf_path: Path,
    state_path: Path,
    chunks_dir: Path,
    marker_client: MarkerClient,
    ov_client: OVClient,
    qdrant_url: str = "http://qdrant:6333",
) -> None:
    """Idempotent ingestion pipeline. Skips if already completed with the same PDF hash.

    After uploading chunks to OpenViking, polls Qdrant until all vectors are indexed
    before returning — ensuring /health only reports ready once the collection is
    fully searchable.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    current_hash = _pdf_hash(pdf_path)

    if state_path.exists():
        state = IngestState.model_validate_json(state_path.read_text())
        if state.completed and state.pdf_hash == current_hash:
            logger.info("Ingestion skipped — already up to date", extra={"pdf_hash": current_hash})
            return

    index_path = chunks_dir / "chunk_index.json"
    if not index_path.exists():
        logger.info("No pre-converted chunks found — calling marker service", extra={"pdf": str(pdf_path)})
        chunks = await marker_client.convert(str(pdf_path))
        chunks_dir.mkdir(parents=True, exist_ok=True)

        index = ChunkIndex()
        for i, chunk in enumerate(chunks):
            filename = f"chunk_{i:04d}_p{chunk.page_number:03d}.md"
            (chunks_dir / filename).write_text(DOC_PREFIX + chunk.text, encoding="utf-8")
            index.entries[filename] = ChunkMeta(
                section_heading=chunk.section_heading,
                page_number=chunk.page_number,
                content_type=chunk.content_type,
            )

        (chunks_dir / "chunk_index.json").write_text(index.model_dump_json(), encoding="utf-8")
        logger.info("Marker conversion done", extra={"chunk_count": len(index.entries)})
    else:
        index = ChunkIndex.model_validate_json(index_path.read_text())
        logger.info("Using pre-converted chunks", extra={"chunk_count": len(index.entries)})

    logger.info("Ingesting chunks into OpenViking", extra={"chunk_count": len(index.entries)})
    await ov_client.ingest_chunks(chunks_dir, sorted(index.entries.keys()))

    # Wait for OV's async embedding queue to fully index all chunks into Qdrant.
    await _wait_for_vectors(qdrant_url, expected=len(index.entries))

    state_path.write_text(
        IngestState(
            completed=True,
            pdf_hash=current_hash,
            chunk_count=len(index.entries),
            ingested_at=datetime.now(tz=timezone.utc),
        ).model_dump_json(),
        encoding="utf-8",
    )
    logger.info("Ingest state saved", extra={"chunk_count": len(index.entries), "pdf_hash": current_hash})
