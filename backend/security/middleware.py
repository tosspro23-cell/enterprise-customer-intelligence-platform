from __future__ import annotations

from collections.abc import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .rate_limit import InMemoryRateLimiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply a process-local request budget to API traffic."""

    def __init__(
        self,
        app,
        *,
        limiter: InMemoryRateLimiter,
        excluded_paths: Iterable[str] = ("/api/health",),
    ) -> None:
        super().__init__(app)
        self.limiter = limiter
        self.excluded_paths = frozenset(excluded_paths)

    @staticmethod
    def _client_key(request: Request) -> str:
        client = request.client
        return client.host if client else "unknown-client"

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS" or request.url.path in self.excluded_paths:
            return await call_next(request)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        decision = self.limiter.allow(self._client_key(request))
        if not decision.allowed:
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={
                    "Retry-After": str(decision.retry_after_seconds),
                    "X-RateLimit-Limit": str(self.limiter.max_requests),
                },
            )
        response = await call_next(request)
        response.headers.setdefault("X-RateLimit-Limit", str(self.limiter.max_requests))
        return response
