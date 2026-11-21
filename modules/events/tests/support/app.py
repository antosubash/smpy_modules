"""The events app the HTTP tests drive.

Real where it matters: the module's own ``register_*`` hooks, its exception
handlers, the framework's sharing router with ``events.calendar`` registered,
and a database holding events' and sharing's tables. Only auth, the host's
``app.state.sm`` and the user directory are stubbed:

* ``X-Test-User`` is the signed-in user's id (absent: anonymous);
* ``X-Test-Perms`` (comma separated) is the resolved permission set;
* ``X-Test-Tenant`` is the tenant the framework resolved
  (``request.state.tenant_id``).

``GET /token`` hands out the session's CSRF token when ``session=True``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest_asyncio
from fastapi import APIRouter, FastAPI, Request
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from sharing.web.endpoints.api import router as sharing_router
from simple_module_core.events import EventBus
from simple_module_core.module_settings import ModuleSettingsRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_core.rate_limit import RateLimitRegistry
from simple_module_core.resources import ResourceTypeRegistry
from simple_module_core.user_directory import DirectoryUser
from simple_module_db import tenant_context
from simple_module_hosting.csrf import get_csrf_token
from simple_module_inertia import InertiaConfig, inertia_dependency_factory
from sm_events.core import boot
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import TenancyMode, configure, install_guard
from sm_events.module import EventsModule
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from tests.pg_support import make_db_state

TEMPLATES = Path(__file__).parent / "templates"
USER_HEADER = "X-Test-User"
PERMS_HEADER = "X-Test-Perms"
TENANT_HEADER = "X-Test-Tenant"


def as_user(user_id: str, *perms: str, tenant: str | None = None) -> dict[str, str]:
    """Headers that make a request come from ``user_id`` holding exactly ``perms``."""
    headers = {USER_HEADER: user_id, PERMS_HEADER: ",".join(perms)}
    if tenant is not None:
        headers[TENANT_HEADER] = tenant
    return headers


class Directory:
    """A user directory over a dict: ``{id: (email, full_name, is_active)}``."""

    entity_type = None

    def __init__(self, users: dict[str, tuple[str, str | None, bool]] | None = None) -> None:
        self.users = users or {}
        self.searches: list[str | None] = []

    def _user(self, uid: str) -> DirectoryUser:
        email, name, active = self.users[uid]
        return DirectoryUser(id=uid, email=email, full_name=name, is_active=active)

    async def get_many(self, db, ids, *, with_roles=False):
        return {i: self._user(i) for i in ids if i in self.users}

    async def search(self, db, term, *, limit):
        self.searches.append(term)
        needle = (term or "").lower()
        hits = [
            self._user(uid)
            for uid, (email, name, _a) in self.users.items()
            if needle in email.lower() or needle in (name or "").lower()
        ]
        return hits[:limit]

    def match_ids(self, term):
        return None


class _Auth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if (user_id := request.headers.get(USER_HEADER)) is not None:
            request.state.user = SimpleNamespace(
                id=user_id, email=f"{user_id}@example.com", name=user_id, roles=[]
            )
            perms = request.headers.get(PERMS_HEADER, "")
            request.state.resolved_permissions = {p for p in perms.split(",") if p}
        tenant = request.headers.get(TENANT_HEADER)
        if tenant:
            request.state.tenant_id = tenant
        if tenant and getattr(request.app.state, "events_bind_tenant", False):
            # What the framework's ``TenantMiddleware`` does on a multi-tenant
            # host: the resolved tenant is also the one bound for the request.
            with tenant_context(tenant):
                return await call_next(request)
        return await call_next(request)


async def build_app(
    *, multi: bool = False, session: bool = False, settings: dict | None = None
) -> tuple[FastAPI, Any]:
    """The app and its ``DatabaseState``; the caller disposes of the engine."""
    state = await make_db_state()
    state.tenant_strict = multi
    app = FastAPI()
    module = EventsModule()
    module.settings = EventsSettings(**(settings or {}))
    permissions = PermissionRegistry()
    module.register_permissions(permissions)
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    app.state.sm = SimpleNamespace(
        db=state,
        event_bus=EventBus(),
        permissions=permissions,
        settings=SimpleNamespace(secret_key="events-test-secret"),
    )
    module.register_settings(app)
    module.register_exception_handlers(app)
    api = APIRouter(prefix=module.meta.route_prefix)
    views = APIRouter(prefix=module.meta.view_prefix)
    module.register_routes(api, views)
    app.include_router(api)
    app.include_router(views)
    # What ``create_app`` does for the sharing module and events' resource type.
    registry = ResourceTypeRegistry()
    module.register_resource_types(registry)
    app.state.sm.resource_types = registry
    app.include_router(sharing_router, prefix="/api/sharing")

    @app.get("/token")
    async def token(request: Request):
        return {"token": get_csrf_token(request)}

    app.add_middleware(_Auth)
    if session:
        app.add_middleware(SessionMiddleware, secret_key="s")
    module.register_middleware(app)
    if multi:
        app.state.sm_events.tenancy = TenancyMode.MULTI
        app.state.events_bind_tenant = True
    else:
        configure(app)
    install_guard(state.sync_session_class)
    app.state.events_module = module
    return app, state


async def build_public_app(
    *,
    multi: bool = False,
    settings: dict | None = None,
    before_wire: Callable[[FastAPI], None] | None = None,
) -> tuple[FastAPI, Any]:
    """:func:`build_app` plus what ``on_startup`` adds for the public surface: the
    routers, the auth exemptions, the rate limits, and a real Inertia adapter (the 404
    page and the public pages render through it). Mounting goes through
    :func:`sm_events.core.boot.wire_public`, as the module's own startup does; ``on_startup``
    itself would re-detect the tenancy mode, which a harness app has no middleware for."""
    app, state = await build_app(multi=multi, settings=settings)
    app.state.inertia_dependency = inertia_dependency_factory(
        InertiaConfig(templates=Jinja2Templates(directory=TEMPLATES), version="test")
    )
    app.state.public_routes = PublicRouteRegistry()
    app.state.rate_limit_rules = RateLimitRegistry()
    if before_wire is not None:
        before_wire(app)
    boot.wire_public(app)
    return app, state


@asynccontextmanager
async def public_http(
    *,
    multi: bool = False,
    settings: dict | None = None,
    before_wire: Callable[[FastAPI], None] | None = None,
) -> AsyncIterator[AsyncClient]:
    app, state = await build_public_app(multi=multi, settings=settings, before_wire=before_wire)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.app = app  # type: ignore[attr-defined]
        http.db_state = state  # type: ignore[attr-defined]
        yield http
    await state.engine.dispose()


@pytest_asyncio.fixture
async def public_client() -> AsyncIterator[AsyncClient]:
    """The public surface, single-tenant, one content locale. Anonymous by default."""
    async with public_http() as http:
        yield http


@pytest_asyncio.fixture
async def public_locales_client() -> AsyncIterator[AsyncClient]:
    """The public surface with English (the default) and German."""
    async with public_http(settings={"content_locales": ("en", "de")}) as http:
        yield http


@pytest_asyncio.fixture
async def public_multi_client() -> AsyncIterator[AsyncClient]:
    """The public surface on a multi-tenant host: the tenant is the one the request resolved
    (``X-Test-Tenant``); with none, the public routes answer 404."""
    async with public_http(multi=True, settings={"content_locales": ("en", "de")}) as http:
        yield http


@pytest_asyncio.fixture
async def events_app() -> AsyncIterator[tuple[FastAPI, Any]]:
    app, state = await build_app()
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(events_app) -> AsyncIterator[AsyncClient]:
    """Anonymous by default. Pass ``headers=as_user(...)`` per request."""
    app, state = events_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.app = app  # type: ignore[attr-defined]
        http.db_state = state  # type: ignore[attr-defined]
        yield http


@pytest_asyncio.fixture
async def multi_client() -> AsyncIterator[AsyncClient]:
    """A multi-tenant app: the tenant is the one the request resolved."""
    app, state = await build_app(multi=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.app = app  # type: ignore[attr-defined]
        http.db_state = state  # type: ignore[attr-defined]
        yield http
    await state.engine.dispose()


@pytest_asyncio.fixture
async def csrf_client() -> AsyncIterator[AsyncClient]:
    """An app with a session mounted, so ``RequiresCsrf`` enforces."""
    app, state = await build_app(session=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.app = app  # type: ignore[attr-defined]
        http.db_state = state  # type: ignore[attr-defined]
        yield http
    await state.engine.dispose()


@pytest_asyncio.fixture
async def locales_client() -> AsyncIterator[AsyncClient]:
    """An app whose content locales are English (the default) and German."""
    app, state = await build_app(settings={"content_locales": ("en", "de")})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.app = app  # type: ignore[attr-defined]
        http.db_state = state  # type: ignore[attr-defined]
        yield http
    await state.engine.dispose()
