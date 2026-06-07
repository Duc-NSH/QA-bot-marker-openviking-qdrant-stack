from __future__ import annotations

import logging

import httpx

from api.models.document import PageChunk

logger = logging.getLogger(__name__)


class MarkerError(RuntimeError):
    """Raised when the Marker service returns an error response."""


class MarkerClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def convert(self, file_path: str) -> list[PageChunk]:
        """Request PDF conversion from the Marker service. Returns extracted chunks."""
        logger.info("Requesting marker conversion", extra={"file_path": file_path})
        try:
            async with httpx.AsyncClient(timeout=1800.0) as client:
                resp = await client.post(
                    f"{self._base_url}/convert",
                    json={"file_path": file_path},
                )
                resp.raise_for_status()
        except httpx.TimeoutException:
            raise TimeoutError(f"Marker conversion timed out after 1800s for {file_path}")
        except httpx.HTTPStatusError as exc:
            raise MarkerError(
                f"Marker returned HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc

        data = resp.json()
        chunks = [PageChunk.model_validate(c) for c in data["chunks"]]
        logger.info("Marker conversion done", extra={"chunk_count": len(chunks)})
        return chunks
