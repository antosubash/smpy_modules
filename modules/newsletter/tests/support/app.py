"""The newsletter app the HTTP tests drive.

Real where it matters: the module's own ``register_settings`` and
``register_routes``, its exception handlers, the framework's settings store and
the generic module-settings API, on a database holding newsletter's, records'
and settings' tables. Only auth and the host's ``app.state.sm`` are stubbed:

* ``x-perms`` (comma separated) is the caller's resolved permission set;
* ``x-roles`` (comma separated) is ``user.roles``, which records' list
  narrowing reads;
* ``x-tenant`` is the tenant the framework resolved (``request.state.tenant_id``).

``GET /token`` hands out the session's CSRF token when ``session=True``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from settings.models import Base as SettingsBase
from settings.web.endpoints.module_api import router as generic_settings_router
from simple_module_core.events import EventBus
from simple_module_core.i18n import I18nRegistry
from simple_module_hosting.csrf import get_csrf_token
from sm_newsletter.core import constants
from sm_newsletter.core.errors import install_exception_handlers
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.core.tenancy import TenancyMode
from sm_newsletter.models import Base
from sm_newsletter.module import NewsletterModule
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from tests.pg_support import _extra_metadata, _pg

SECRET = "test-host-secret"


def _csv(raw: str) -> list[str]:
    return [p for p in raw.split(",") if p]


class _Auth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        roles = _csv(request.headers.get("x-roles", ""))
        request.state.user = SimpleNamespace(id="u", email="u@example.com", name="U", roles=roles)
        request.state.resolved_permissions = set(_csv(request.headers.get("x-perms", "")))
        if tenant := request.headers.get("x-tenant"):
            request.state.tenant_id = tenant
        return await call_next(request)


class _FakeInertia:
    """Answers a view with the component and props it would render, as JSON."""

    def __init__(self) -> None:
        self.shared: dict[str, Any] = {}

    def share(self, **props: Any) -> None:
        self.shared.update(props)

    async def render(self, component: str, props: dict | None = None) -> JSONResponse:
        return JSONResponse({"component": component, "props": {**self.shared, **(props or {})}})


async def build_app(
    *,
    multi: bool = False,
    session: bool = False,
    settings: dict | None = None,
    file: Path | None = None,
) -> tuple[FastAPI, Any]:
    """The app and its ``DatabaseState``; the caller disposes of the engine.

    ``settings`` pins :class:`NewsletterSettings` fields without the database;
    ``file`` gives SQLite a file database with one connection per session (a race)."""
    state = await _pg.make_db_state(
        Base.metadata, *_extra_metadata(), SettingsBase.metadata, file=file
    )
    app = FastAPI()
    app.state.sm = SimpleNamespace(
        db=state,
        event_bus=EventBus(),
        i18n_registry=I18nRegistry("en", ("en",)),
        settings=SimpleNamespace(secret_key=SECRET, i18n_default_locale="en"),
    )
    module = NewsletterModule()
    if settings is not None:
        module.settings = NewsletterSettings(**settings)
    module.register_settings(app)
    if multi:
        app.state.sm_newsletter.tenancy = TenancyMode.MULTI
    api = APIRouter(prefix=constants.ROUTE_PREFIX_API)
    views = APIRouter(prefix=constants.VIEW_PREFIX)
    module.register_routes(api, views)
    app.include_router(api)
    app.include_router(views)
    app.state.inertia_dependency = lambda request, _=None: _FakeInertia()
    app.include_router(generic_settings_router, prefix="/api/settings")
    install_exception_handlers(app)

    @app.get("/token")
    async def token(request: Request):
        return {"token": get_csrf_token(request)}

    app.add_middleware(_Auth)
    if session:
        app.add_middleware(SessionMiddleware, secret_key="s")
    return app, state
