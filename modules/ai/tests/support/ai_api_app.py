"""The settings API app the web tests drive (assembled by hand, news-conftest style).

An auth stub middleware grants the permissions, the module-global holder
carries the settings (with a stored chat key), and ``AiService.apply`` is
replaced to capture the changes - persistence itself is framework code with
its own tests upstream. ``write_through`` also applies them to the live
settings, for tests that read the result back.

A uniquely named module, not ``conftest``: see ``ai_test_stubs``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sm_ai.core import constants, crypto, services
from sm_ai.core.settings import AiSettings
from sm_ai.web.service import AiService

STORED_KEY = "sk-stored"


@asynccontextmanager
async def api_client(
    monkeypatch, auth, *, secret: str, write_through: bool = False
) -> AsyncIterator[AsyncClient]:
    """A client for ``/api/ai``; ``client.applied`` lists every captured change set."""
    from simple_module_db.deps import get_db
    from sm_ai.web.endpoints.api import router as api_router

    monkeypatch.setenv("SM_SECRET_KEY", secret)
    services.install(
        services.AiServices(settings=AiSettings(chat_api_key=crypto.encrypt_value(STORED_KEY)))
    )
    applied: list[dict] = []

    async def _fake_apply(self, changes):
        applied.append(changes)
        if write_through:
            for field, value in changes.items():
                setattr(services.current_settings(), field, value)
        return self.current()

    monkeypatch.setattr(AiService, "apply", _fake_apply)
    app = FastAPI()
    app.add_middleware(auth)
    # apply() is stubbed, so no endpoint touches the session; get_db still
    # resolves, and without a host there is no app.state.sm to build one from.
    app.dependency_overrides[get_db] = lambda: None
    prefixed = APIRouter(prefix=constants.ROUTE_PREFIX_API)
    prefixed.include_router(api_router)
    app.include_router(prefixed)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            http.applied = applied
            yield http
    finally:
        services.reset()
