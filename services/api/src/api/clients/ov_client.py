from __future__ import annotations

import logging
from pathlib import Path

import httpx

from api.constants import QUERY_PREFIX, RESOURCES_URI

logger = logging.getLogger(__name__)


class OVClientError(RuntimeError):
    """Raised when OpenViking returns an unexpected error response."""


class OVClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        account: str = "default",
        user: str = "api",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._account = account
        self._user = user
        self._api_key = api_key
        self._headers: dict[str, str] = {}
        if api_key:
            self._headers["X-Api-Key"] = api_key
        self._headers["X-OpenViking-Account"] = account
        self._headers["X-OpenViking-User"] = user

    async def ensure_user(self) -> None:
        """Create account user if not present (idempotent — 409 is OK)."""
        admin_headers = {"X-Api-Key": self._api_key} if self._api_key else {}
        async with httpx.AsyncClient(timeout=30.0, headers=admin_headers) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/admin/accounts/{self._account}/users",
                json={"user_id": self._user, "role": "admin"},
            )
            if resp.status_code not in (200, 409):
                raise OVClientError(
                    f"ensure_user failed: HTTP {resp.status_code} — {resp.text[:200]}"
                )

    async def ingest_chunks(self, chunks_dir: Path, filenames: list[str]) -> None:
        """Upload chunk files to OpenViking with create-or-replace semantics.

        Embeddings are queued asynchronously by OV; call sites must separately
        wait for the Qdrant vector count to reach the expected value before
        serving queries.
        """
        await self.ensure_user()
        logger.info("Uploading chunks to OpenViking", extra={"count": len(filenames)})

        async with httpx.AsyncClient(timeout=60.0, headers=self._headers) as client:
            for filename in filenames:
                content = (chunks_dir / filename).read_text(encoding="utf-8")
                uri = f"{RESOURCES_URI}/{filename}"
                resp = await client.post(
                    f"{self._base_url}/api/v1/content/write",
                    json={"uri": uri, "content": content, "mode": "create", "wait": False},
                )
                if resp.status_code == 409:
                    resp = await client.post(
                        f"{self._base_url}/api/v1/content/write",
                        json={"uri": uri, "content": content, "mode": "replace", "wait": False},
                    )
                if not resp.is_success:
                    raise OVClientError(
                        f"content/write failed for {filename}: HTTP {resp.status_code} — {resp.text[:200]}"
                    )
                logger.debug("Chunk uploaded", extra={"filename": filename, "status": resp.status_code})

        logger.info("All chunks uploaded; embeddings queued in background")

    async def find(self, question: str, limit: int = 15) -> list[dict]:
        """Semantic search using the instruction-prefixed query against the BCTN collection."""
        prefixed = QUERY_PREFIX + question
        async with httpx.AsyncClient(timeout=180.0, headers=self._headers) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/search/find",
                json={"query": prefixed, "limit": limit, "target_uri": RESOURCES_URI},
            )
            if not resp.is_success:
                raise OVClientError(
                    f"search/find failed: HTTP {resp.status_code} — {resp.text[:200]}"
                )
            result = resp.json().get("result") or {}
            resources = result.get("resources", [])
            logger.debug("OV search complete", extra={"hits": len(resources)})
            return resources
