"""Shared setup for test_tenancy_primitives."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import current_tenant_id
from simple_module_hosting.middleware import TenantMiddleware
from sm_records.core import constants
from sm_records.core.tenancy import (
    TenancyMode,
    bind_admin,
    bind_public,
)
from sm_records.web.endpoints.api._errors import RecordsErrorRoute
from starlette.middleware.base import BaseHTTPMiddleware

_REPO = Path(__file__).resolve().parents[4]


def _real_app(monkeypatch, *, multi: bool):
    """``create_app`` — the stack the framework really builds. It resolves the
    host's templates from the project root it computed at import (the working
    directory then), so that is pointed at this repo's root."""
    if not (_REPO / "host" / "templates").is_dir():  # pragma: no cover - module-only checkout
        pytest.skip("no host checkout to build a real app from")
    from simple_module_hosting import Settings, app_builder, create_app

    monkeypatch.setattr(app_builder, "_PROJECT_ROOT", _REPO)
    return create_app(
        Settings(
            environment="testing",
            secret_key="tenancy-test",
            multi_tenant=multi,
            tenant_header="X-Tenant-ID" if multi else "",
        )
    )


def _request(mode: TenancyMode, *, user=None, state_tenant=None):
    services = SimpleNamespace(tenancy=mode)
    app = SimpleNamespace(state=SimpleNamespace(**{constants.PACKAGE: services}))
    return SimpleNamespace(app=app, state=SimpleNamespace(user=user, tenant_id=state_tenant))


class _UserFromHeader(BaseHTTPMiddleware):
    """``X-Test-User-Tenant`` becomes a signed-in user with that tenant
    (``-`` for none) — outermost, where the framework's AuthMiddleware sits."""

    async def dispatch(self, request, call_next):  # type: ignore[override]
        raw = request.headers.get("X-Test-User-Tenant")
        if raw is not None:
            request.state.user = SimpleNamespace(tenant_id=None if raw == "-" else raw)
        return await call_next(request)


def _bound_app(*, multi: bool) -> FastAPI:
    app = FastAPI()
    for path, dependency in (("/admin", bind_admin), ("/public", bind_public)):
        router = APIRouter(route_class=RecordsErrorRoute, dependencies=[Depends(dependency)])

        @router.get(path)
        async def seen() -> dict:
            return {"tenant": current_tenant_id.get()}

        app.include_router(router)
    if multi:
        app.add_middleware(TenantMiddleware, header="X-Tenant-ID")
    app.add_middleware(_UserFromHeader)
    return app


async def _get(app: FastAPI, path: str, **headers: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(path, headers=headers)
