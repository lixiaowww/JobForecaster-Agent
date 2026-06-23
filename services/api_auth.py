"""Optional API key auth and in-memory rate limiting for the REST server."""
from __future__ import annotations

import os
import time
from collections import defaultdict

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_429_TOO_MANY_REQUESTS

from services.config_loader import load_config

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def configured_api_key() -> str | None:
    """API key from env (preferred) or config. Never commit real keys."""
    key = os.environ.get("FORECASTER_API_KEY", "").strip()
    if key:
        return key
    cfg_key = load_config().get("api", {}).get("api_key")
    return str(cfg_key).strip() if cfg_key else None


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
) -> None:
    """Enforce X-API-Key when FORECASTER_API_KEY is set; open in local dev otherwise."""
    expected = configured_api_key()
    if not expected:
        return
    if not api_key or api_key != expected:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )


class RateLimiter:
    """Simple per-client-IP sliding window (in-memory, single process)."""

    def __init__(self, requests_per_minute: int = 60):
        self.limit = max(1, requests_per_minute)
        self._hits: dict[str, list[float]] = defaultdict(list)

    def _client_id(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def check(self, request: Request) -> None:
        now = time.monotonic()
        window = 60.0
        cid = self._client_id(request)
        hits = [t for t in self._hits[cid] if now - t < window]
        if len(hits) >= self.limit:
            raise HTTPException(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({self.limit} requests/minute)",
            )
        hits.append(now)
        self._hits[cid] = hits

