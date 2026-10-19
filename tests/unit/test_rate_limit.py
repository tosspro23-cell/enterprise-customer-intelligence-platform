from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.security.middleware import RateLimitMiddleware
from backend.security.rate_limit import InMemoryRateLimiter


def test_fixed_window_limiter_expires_and_returns_retry_after() -> None:
    now = [100.0]
    limiter = InMemoryRateLimiter(
        max_requests=2,
        window_seconds=10,
        clock=lambda: now[0],
    )

    assert limiter.allow("client").allowed
    assert limiter.allow("client").allowed
    blocked = limiter.allow("client")
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 10

    now[0] = 110.0
    assert limiter.allow("client").allowed


def test_middleware_limits_api_traffic_but_excludes_health() -> None:
    application = FastAPI()
    application.add_middleware(
        RateLimitMiddleware,
        limiter=InMemoryRateLimiter(max_requests=1, window_seconds=60),
    )

    @application.get("/api/health")
    async def health():
        return {"status": "ok"}

    @application.get("/api/resource")
    async def resource():
        return {"status": "ok"}

    client = TestClient(application)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/resource").status_code == 200
    limited = client.get("/api/resource")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
