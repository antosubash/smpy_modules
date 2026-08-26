"""Shared fixtures for the news integration tests.

News owns its content, so the harness creates exactly one module's tables. That
is the headline change from the sidecar era, when every meaningful query was a
join and the fixtures had to stand up pagebuilder's schema alongside news' own
for any test to run at all.

The rest mirrors the framework's house style — ``StaticPool`` so every session
sees the same ``:memory:`` instance, ``register_listeners`` so ``get_db``
actually commits, and a stub auth middleware standing in for
``simple_module_auth``.

Articles are created directly through the model rather than through the API.
These are unit-ish integration tests: what matters is the row a query finds, not
the workflow that produced it — ``test_workflow`` covers that separately.

Pagebuilder's tables are created too, but only when it happens to be importable
— which it is in this workspace, and is not on a host that installed news alone.
That models the real dual-module deployment, where the optional extra is
installed *and* migrated, so the admin search screen's Pages and Media sections
have something to read. ``test_search`` covers the other shape by making
``available()`` answer False.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI, Request
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from inertia import InertiaConfig, inertia_dependency_factory
from news.constants import PERM_EDIT, PERM_PUBLISH, PERM_VIEW
from news.models import Base as NewsBase
from news.module import NewsModule
from simple_module_core.permissions import PermissionRegistry
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

_SHELL = (
    # Shaped like the host's page, not a bare `<html></html>`: a `<head>` with a
    # fixed app title and the `{% inertia_head %}` slot that stays empty without
    # SSR. `endpoints.public._head` writes an article's real metadata into that
    # head, and against a stub with nowhere to write it every test asserting on
    # server-rendered metadata would pass by asserting nothing.
    "<html><head><title>SimpleModule</title>{% inertia_head %}</head>"
    "<body>{% inertia_body %}</body></html>"
)


async def _create_tables(conn) -> None:
    """News' own tables, plus the optional neighbour's where it is installed.

    Only one ``create_all`` is required. The sidecar needed both or no test
    could run at all, because every meaningful query was a join.
    """
    await conn.run_sync(NewsBase.metadata.create_all)
    try:
        from pagebuilder.models import Base as PagebuilderBase
    except ImportError:  # pragma: no cover - the news-alone host
        return
    await conn.run_sync(PagebuilderBase.metadata.create_all)


@pytest.fixture(autouse=True)
def _no_leaked_module_state():
    """The settings the module publishes at startup are process-global.

    Without this a test that boots the module changes the public URL every later
    test in the same process reads back.
    """
    from news import settings as news_settings

    news_settings.reset()
    yield
    news_settings.reset()


ROLE_EDITOR = "news-editor"
#: ``news.edit`` without ``news.publish`` — the case every workflow route that
#: puts something in front of readers has to refuse. This separation used to be
#: pagebuilder's, enforced by requiring its permissions on the routes that wrote
#: a page; owning the content means owning the separation.
ROLE_AUTHOR = "news-author"
ROLE_VIEWER = "news-viewer"


def _stub_user(roles: tuple[str, ...]) -> SimpleNamespace:
    """Stand in for ``auth.UserContext``.

    Deliberately carries no ``permissions`` attribute — the real UserContext has
    none either, and a fixture that invented one would hide exactly the bug
    ``may_see_drafts`` used to have.
    """
    return SimpleNamespace(
        id="test-user",
        email="test@example.com",
        name="Test User",
        roles=list(roles),
    )


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Populate ``request.state.user`` the way the host's auth middleware would.

    ``user=None`` leaves the request anonymous, which is what the public feed
    block looks like.
    """

    def __init__(self, app: Any, user: Any) -> None:
        super().__init__(app)
        self._user = user

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if self._user is not None:
            request.state.user = self._user
        return await call_next(request)


async def _build_app(user: Any) -> tuple[FastAPI, Any]:
    module = NewsModule()
    app = FastAPI()

    api_router = APIRouter(prefix=module.meta.route_prefix, tags=[module.meta.name])
    view_router = APIRouter(prefix=module.meta.view_prefix, tags=[module.meta.name])
    module.register_routes(api_router, view_router)
    app.include_router(api_router)
    app.include_router(view_router)

    db_state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    register_listeners(db_state)
    async with db_state.engine.begin() as conn:
        await _create_tables(conn)

    registry = PermissionRegistry()
    registry.add_group("News", [PERM_VIEW, PERM_EDIT, PERM_PUBLISH])
    registry.map_role(ROLE_EDITOR, [PERM_VIEW, PERM_EDIT, PERM_PUBLISH])
    registry.map_role(ROLE_AUTHOR, [PERM_VIEW, PERM_EDIT])
    registry.map_role(ROLE_VIEWER, [PERM_VIEW])
    app.state.sm = SimpleNamespace(db=db_state, permissions=registry)
    module.register_settings(app)

    # Minimal Inertia config — enough to render without the real host
    # templates. News serves its own public viewer, so the render happens here.
    # See ``_SHELL`` for why it is shaped like the host's page rather than a stub.
    templates_dir = Path(tempfile.mkdtemp()) / "templates"
    templates_dir.mkdir(parents=True)
    (templates_dir / "index.html").write_text(_SHELL)
    app.state.inertia_dependency = inertia_dependency_factory(
        InertiaConfig(
            environment="development",
            version="1.0",
            dev_url="http://localhost:5050",
            templates=Jinja2Templates(directory=str(templates_dir)),
            root_template_filename="index.html",
            entrypoint_filename="main.tsx",
            root_directory=".",
            use_flash_errors=True,
        )
    )

    app.add_middleware(_StubAuthMiddleware, user=user)
    # Inertia reads flashed errors off the session on every render, so the
    # public viewer cannot answer at all without this. Added last so it ends up
    # outermost at runtime — Starlette runs the last-added middleware first on
    # the way in — which matches the host's own order.
    app.add_middleware(SessionMiddleware, secret_key="news-tests")

    # Mounts the public viewer and the admin search screen — production calls
    # this from the lifespan startup hook.
    await module.on_startup(app)
    return app, db_state


@pytest_asyncio.fixture
async def db_state() -> AsyncIterator[Any]:
    """A bare database with the module's tables, for direct service tests."""
    state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await _create_tables(conn)
    yield state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def db(db_state) -> AsyncIterator[AsyncSession]:
    async with db_state.session_factory() as session:
        yield session


async def _client(user: Any) -> AsyncIterator[AsyncClient]:
    app, state = await _build_app(user)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        client.db_state = state  # type: ignore[attr-defined]
        yield client
    await state.engine.dispose()


@pytest_asyncio.fixture
async def editor_client() -> AsyncIterator[AsyncClient]:
    """`news.edit` *and* `news.publish` — not WILDCARD."""
    async for client in _client(_stub_user((ROLE_EDITOR,))):
        yield client


@pytest_asyncio.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    """Authenticated as `admin`, which resolves to WILDCARD rather than to
    a literal `news.edit` — the case a naive membership test would miss."""
    async for client in _client(_stub_user(("admin",))):
        yield client


@pytest_asyncio.fixture
async def author_client() -> AsyncIterator[AsyncClient]:
    """`news.edit`, but not `news.publish`.

    Everything that puts an article in front of readers has to refuse this
    caller, or owning the workflow quietly widened what `news.edit` grants.
    """
    async for client in _client(_stub_user((ROLE_AUTHOR,))):
        yield client


@pytest_asyncio.fixture
async def viewer_client() -> AsyncIterator[AsyncClient]:
    """Authenticated but without `news.edit`."""
    async for client in _client(_stub_user((ROLE_VIEWER,))):
        yield client


@pytest_asyncio.fixture
async def anon_client() -> AsyncIterator[AsyncClient]:
    """No session at all — what the public feed block looks like."""
    async for client in _client(None):
        yield client
