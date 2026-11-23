"""The request-context middleware: the current request inside a request, ``None`` outside."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sm_events.core.tenancy.request_context import RequestContextMiddleware, current_request


async def test_current_request_inside_and_outside():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/probe")
    async def probe():
        request = current_request()
        return {"path": request.url.path if request is not None else None}

    assert current_request() is None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        got = await client.get("/probe")
    assert got.json() == {"path": "/probe"}
    assert current_request() is None
