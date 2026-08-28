"""Shared fixtures for pagebuilder integration tests.

Each fixture spins up a fully-wired test app: in-memory aiosqlite
backing the ``get_db`` dep (with audit listeners attached so writes
actually commit), ``SessionMiddleware`` so CSRF + session state work,
a minimal Inertia config so the public viewer can render, and a fresh
``MediaService`` rooted at ``tmp_path`` so uploads never escape the
per-test sandbox.

The fixtures wire the module via its own ``register_*`` hooks rather
than re-implementing them; the only test-specific seam is the
``module.settings`` pre-population, which is how production code can
also override settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from inertia import InertiaConfig, inertia_dependency_factory
from pagebuilder.models import Base
from pagebuilder.module import PagebuilderModule
from pagebuilder.permissions import (
    ALL_PERMISSIONS,
    PERM_APPROVE,
    PERM_EDIT,
    PERM_PUBLISH,
    ROLE_APPROVER,
    ROLE_EDITOR,
)
from pagebuilder.settings import PagebuilderSettings
from simple_module_core.permissions import PermissionRegistry
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy.pool import StaticPool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

_SESSION_SECRET = "pagebuilder-tests-secret"

# Tiny valid PNG header — matches the sniffer's PNG signature. Lives at
# module scope so upload tests can import it instead of redefining.
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 16


def _stub_user(roles: tuple[str, ...] = ("admin",)) -> SimpleNamespace:
    return SimpleNamespace(
        id="test-user",
        email="test@example.com",
        name="Test User",
        roles=list(roles),
    )


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Populate ``request.state.user`` the way the host's auth middleware would.

    Production runs ``simple_module_auth``'s session middleware before
    every request and stashes a ``UserContext`` on ``request.state``.
    The pagebuilder test harness doesn't mount that middleware, so we
    drop a minimal stand-in here whenever a fixture wants requests to
    look authenticated. Without it, ``simple_module_hosting``'s
    ``RequiresPermission`` would 401 every protected endpoint.
    """

    def __init__(self, app: Any, user: Any) -> None:
        super().__init__(app)
        self._user = user

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request.state.user = self._user
        return await call_next(request)


async def _build_app(
    tmp_path,
    *,
    requires_auth: bool,
    csrf_protect: bool,
    inject_user: bool,
    user_roles: tuple[str, ...] = ("admin",),
    role_map: dict[str, list[str]] | None = None,
) -> tuple[FastAPI, Callable[[], Awaitable[None]]]:
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    module = PagebuilderModule()
    # Pre-seed module settings so the register_* hooks below see the
    # test-override flags instead of scanning env vars.
    module.settings = PagebuilderSettings(
        media_root=media_root,
        requires_auth=requires_auth,
        csrf_protect=csrf_protect,
    )

    app = FastAPI()
    module.register_settings(app)
    module.register_middleware(app)

    # Mirror ``wire_module_routes``: build prefixed routers, hand them
    # to the module, then mount them on the app.
    api_router = APIRouter(prefix=module.meta.route_prefix, tags=[module.meta.name])
    view_router = APIRouter(prefix=module.meta.view_prefix, tags=[module.meta.name])
    module.register_routes(api_router, view_router)
    app.include_router(api_router)
    app.include_router(view_router)

    # In-memory DB + auto-created schema. ``StaticPool`` reuses a single
    # connection so every ``async with factory()`` sees the same
    # ``:memory:`` instance — without it each connection gets a fresh
    # DB and rows vanish between requests.
    #
    # ``register_listeners`` attaches the audit hook that flips the
    # ``has_writes`` flag; ``get_db`` checks it to decide between commit
    # and rollback. Skipping that turned every API write into a silent
    # rollback in earlier iterations of this fixture.
    db_state = init_db(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    register_listeners(db_state)
    async with db_state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Wire up a permissions registry so RequiresPermission can resolve
    # non-admin roles. Without this, the framework's role-map fallback
    # is empty and editor/publisher fixtures would silently get zero
    # perms (the admin stub still works via DEFAULT_ROLE_PERMISSIONS).
    sm_namespace: SimpleNamespace = SimpleNamespace(db=db_state)
    if role_map is not None:
        registry = PermissionRegistry()
        registry.add_group("PageBuilder", list(ALL_PERMISSIONS))
        for role, perms in role_map.items():
            registry.map_role(role, perms)
        sm_namespace.permissions = registry
    app.state.sm = sm_namespace

    # Minimal Inertia config — enough to short-circuit on
    # ``X-Inertia: true`` without needing the real host templates.
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "index.html").write_text("<html></html>")
    inertia_config = InertiaConfig(
        environment="development",
        version="1.0",
        dev_url="http://localhost:5050",
        templates=Jinja2Templates(directory=str(templates_dir)),
        root_template_filename="index.html",
        entrypoint_filename="main.tsx",
        root_directory=".",
        use_flash_errors=True,
    )
    app.state.inertia_dependency = inertia_dependency_factory(inertia_config)

    if inject_user:
        # Added before SessionMiddleware so it sits inside it at runtime
        # (Starlette wraps outermost = last-added). Position doesn't
        # actually matter here — stub-auth just stamps request.state —
        # but keeping it inside the session matches the production order.
        app.add_middleware(_StubAuthMiddleware, user=_stub_user(user_roles))

    # SessionMiddleware is added last so it ends up outermost at runtime
    # (Starlette runs the last-added middleware first on the way in).
    # CsrfCookieMiddleware was already added by ``register_middleware``
    # above — it needs to wrap outside the session so the session is
    # fully populated by the time the cookie mirror reads it.
    app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET)

    # Mount the public viewer + media static (production calls this in
    # the lifespan startup hook).
    await module.on_startup(app)

    async def cleanup() -> None:
        await db_state.engine.dispose()

    return app, cleanup


@asynccontextmanager
async def _client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _client_fixture(
    tmp_path,
    *,
    requires_auth: bool,
    csrf_protect: bool,
    inject_user: bool,
    user_roles: tuple[str, ...] = ("admin",),
    role_map: dict[str, list[str]] | None = None,
) -> AsyncIterator[AsyncClient]:
    app, cleanup = await _build_app(
        tmp_path,
        requires_auth=requires_auth,
        csrf_protect=csrf_protect,
        inject_user=inject_user,
        user_roles=user_roles,
        role_map=role_map,
    )
    try:
        async with _client_for(app) as c:
            yield c
    finally:
        await cleanup()


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Unauthenticated client — admin endpoints return 401."""
    async for c in _client_fixture(
        tmp_path, requires_auth=True, csrf_protect=False, inject_user=False
    ):
        yield c


@pytest.fixture
async def authed_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Auth-bypassed client — every admin endpoint runs as an admin user."""
    async for c in _client_fixture(
        tmp_path, requires_auth=True, csrf_protect=False, inject_user=True
    ):
        yield c


@pytest.fixture
async def csrf_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Auth-bypassed client with CSRF enabled — the CSRF tests' workhorse."""
    async for c in _client_fixture(
        tmp_path, requires_auth=True, csrf_protect=True, inject_user=True
    ):
        yield c


@pytest.fixture
async def open_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Public client — auth + CSRF both disabled via settings."""
    async for c in _client_fixture(
        tmp_path, requires_auth=False, csrf_protect=False, inject_user=False
    ):
        yield c


@pytest.fixture
async def editor_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Stub user holding only ``pagebuilder.edit`` (no publish / approve)."""
    async for c in _client_fixture(
        tmp_path,
        requires_auth=True,
        csrf_protect=False,
        inject_user=True,
        user_roles=(ROLE_EDITOR,),
        role_map={ROLE_EDITOR: [PERM_EDIT]},
    ):
        yield c


@pytest.fixture
async def approver_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Stub user holding edit + publish + approve."""
    async for c in _client_fixture(
        tmp_path,
        requires_auth=True,
        csrf_protect=False,
        inject_user=True,
        user_roles=(ROLE_APPROVER,),
        role_map={ROLE_APPROVER: [PERM_EDIT, PERM_PUBLISH, PERM_APPROVE]},
    ):
        yield c


async def create_draft(
    client: AsyncClient,
    *,
    slug: str = "post",
    title: str = "Draft",
    draft_data: dict | None = None,
) -> dict:
    """POST a fresh draft page and return the API body."""
    response = await client.post(
        "/api/pagebuilder/pages",
        json={
            "title": title,
            "slug": slug,
            "draft_data": draft_data
            if draft_data is not None
            else {"content": ["hello"]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
