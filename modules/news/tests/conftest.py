"""Shared fixtures for the news integration tests.

News is a sidecar over pagebuilder, so every meaningful query is a join and the
harness has to create *both* modules' tables against one in-memory database.
That is the only real difference from pagebuilder's own conftest; the rest
mirrors it — ``StaticPool`` so every session sees the same ``:memory:``
instance, ``register_listeners`` so ``get_db`` actually commits, and a stub auth
middleware standing in for ``simple_module_auth``.

Pages are created directly through the ``Page`` model rather than through
pagebuilder's API. These are news tests: what matters is the row the join finds,
not the workflow that produced it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from news.constants import PERM_EDIT, PERM_VIEW
from news.models import Base as NewsBase
from news.module import NewsModule
from pagebuilder.models import Base as PagebuilderBase
from pagebuilder.models import Page, PageStatus
from pagebuilder.permissions import PERM_EDIT as PAGE_EDIT
from pagebuilder.permissions import PERM_PUBLISH as PAGE_PUBLISH
from simple_module_core.permissions import PermissionRegistry
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import StaticPool
from starlette.middleware.base import BaseHTTPMiddleware


@pytest.fixture(autouse=True)
def _no_leaked_module_state():
    """Both registries the module writes to at startup are process-global.

    ``on_startup`` registers news' slug claim with pagebuilder and publishes the
    resolved settings; without this a test that boots the module changes the
    answers of every later test in the same process.
    """
    from news import settings as news_settings
    from pagebuilder import public_claims

    public_claims.reset()
    news_settings.reset()
    yield
    public_claims.reset()
    news_settings.reset()


ROLE_EDITOR = "news-editor"
#: ``news.edit`` and nothing of pagebuilder's — the case the page-writing
#: routes must refuse.
ROLE_NEWS_ONLY = "news-only"
ROLE_VIEWER = "news-viewer"


def _stub_user(roles: tuple[str, ...]) -> SimpleNamespace:
    """Stand in for ``auth.UserContext``.

    Deliberately carries no ``permissions`` attribute — the real UserContext has
    none either, and a fixture that invented one would hide exactly the bug
    ``_may_see_drafts`` used to have.
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
        # Both metadatas: an article is only ever read through a join to a page.
        await conn.run_sync(PagebuilderBase.metadata.create_all)
        await conn.run_sync(NewsBase.metadata.create_all)

    registry = PermissionRegistry()
    registry.add_group("News", [PERM_VIEW, PERM_EDIT])
    # An article author needs pagebuilder's permissions too: creating and
    # publishing an article writes a *page*, and news does not get to route
    # around the editor → publisher separation that module maintains.
    registry.map_role(ROLE_EDITOR, [PERM_VIEW, PERM_EDIT, PAGE_EDIT, PAGE_PUBLISH])
    registry.map_role(ROLE_NEWS_ONLY, [PERM_VIEW, PERM_EDIT])
    registry.map_role(ROLE_VIEWER, [PERM_VIEW])
    app.state.sm = SimpleNamespace(db=db_state, permissions=registry)

    app.add_middleware(_StubAuthMiddleware, user=user)
    return app, db_state


@pytest_asyncio.fixture
async def db_state() -> AsyncIterator[Any]:
    """A bare database with both modules' tables, for direct service tests."""
    state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(PagebuilderBase.metadata.create_all)
        await conn.run_sync(NewsBase.metadata.create_all)
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
    """Authenticated as a role that maps to `news.edit` — not to WILDCARD."""
    async for client in _client(_stub_user((ROLE_EDITOR,))):
        yield client


@pytest_asyncio.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    """Authenticated as `admin`, which resolves to WILDCARD rather than to
    a literal `news.edit` — the case a naive membership test would miss."""
    async for client in _client(_stub_user(("admin",))):
        yield client


@pytest_asyncio.fixture
async def news_only_client() -> AsyncIterator[AsyncClient]:
    """`news.edit`, but none of pagebuilder's permissions.

    Everything that writes a page on the author's behalf has to refuse this
    caller, or moving those writes server-side quietly widened what `news.edit`
    grants.
    """
    async for client in _client(_stub_user((ROLE_NEWS_ONLY,))):
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


async def make_page(
    db: AsyncSession,
    *,
    slug: str,
    title: str = "A page",
    status: PageStatus = PageStatus.PUBLISHED,
    meta_description: str | None = None,
    og_image: str | None = None,
) -> Page:
    """Insert a page for an article to hang off. Committed, so an API request
    on another session sees it."""
    page = Page(
        slug=slug,
        title=title,
        status=status,
        draft_data={},
        meta_description=meta_description,
        og_image=og_image,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page


@pytest.fixture
def make_page_factory():
    return make_page
