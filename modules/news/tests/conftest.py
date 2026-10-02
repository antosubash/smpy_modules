"""Shared fixtures for the news integration tests.

News owns its content, so the harness creates exactly one module's tables. That
is the headline change from the sidecar era, when every meaningful query was a
join and the fixtures had to stand up pagebuilder's schema alongside news' own
for any test to run at all.

The rest mirrors the framework's house style — the database comes from
``pg_support.make_db_state`` (in-memory SQLite on a ``StaticPool`` by default,
the Postgres database ``SM_TEST_DATABASE_URL`` names when it is set, with
``register_listeners`` attached either way so ``get_db`` actually commits), and
a stub auth middleware stands in for ``simple_module_auth``.

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
from fastapi import APIRouter, FastAPI
from fastapi.templating import Jinja2Templates
from httpx import ASGITransport, AsyncClient
from news.constants import PERM_EDIT, PERM_PUBLISH, PERM_VIEW
from news.module import NewsModule

# ``pg_support`` owns the one decision both database fixtures make: in-memory
# SQLite, or the Postgres database ``SM_TEST_DATABASE_URL`` names. It is also
# where "news' tables, plus pagebuilder's where installed" is spelled out.
from pg_support import arm_reset, make_db_state
from settings.module_registry import ModuleSettingsRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_inertia import InertiaConfig, inertia_dependency_factory
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware
from stub_auth import StubAuthMiddleware, stub_user

_SHELL = (
    # Shaped like the host's page, not a bare `<html></html>`: a `<head>` with a
    # fixed app title and the `{% inertia_head %}` slot that stays empty without
    # SSR. `endpoints.public._head` writes an article's real metadata into that
    # head, and against a stub with nowhere to write it every test asserting on
    # server-rendered metadata would pass by asserting nothing.
    "<html><head><title>SimpleModule</title>{% inertia_head %}</head>"
    "<body>{% inertia_body %}</body></html>"
)


@pytest.fixture(autouse=True)
def _arm_database_reset():
    """Every test starts from an empty database.

    A no-op on SQLite, where each test builds its own ``:memory:`` one and
    there is nothing to empty. On Postgres it is what makes the *first*
    database a test asks for a clean one — a test taking both ``db`` and a
    client fixture has two independent databases on SQLite and two windows
    onto one database on Postgres. See ``tests/pg_support.py`` at the repo
    root.
    """
    arm_reset()
    yield


@pytest.fixture(autouse=True)
def _no_leaked_module_state():
    """Every registry the module writes to at startup is process-global.

    ``on_startup`` publishes the resolved settings and mounts one public router
    per content locale; without this a test that boots the module changes the
    public URL every later test in the same process reads back.

    Pagebuilder's content locales are the other half: news reads them to decide
    which languages to mount, so a multilingual test that left them behind
    would mount the *next* test's routes in whatever language it configured —
    an order-dependent failure with no visible cause.

    There is no slug claim to reset any more. An article was a pagebuilder page
    when there was, and it is not one now.
    """
    from news import settings as news_settings
    from pagebuilder import locales

    news_settings.reset()
    locales.reset()
    yield
    news_settings.reset()
    locales.reset()


@pytest.fixture
def bilingual():
    """Configure the site to publish in English (default) and German.

    Set through ``pagebuilder.locales`` because that is where the site's content
    languages live. An article is no longer a page — it owns its own content and
    its own ``locale`` — but which languages the *site* publishes in is still one
    decision, not two, and offering a language the rest of the site does not have
    would strand every article written in it. Reset by ``_no_leaked_module_state``
    above.
    """
    from pagebuilder import locales
    from pagebuilder.settings import PagebuilderSettings

    locales.use(
        PagebuilderSettings(content_locales=("en", "de"), default_content_locale="en")
    )
    return ("en", "de")


ROLE_EDITOR = "news-editor"
#: ``news.edit`` without ``news.publish`` — the case every workflow route that
#: puts something in front of readers has to refuse. This separation used to be
#: pagebuilder's, enforced by requiring its permissions on the routes that wrote
#: a page; owning the content means owning the separation.
ROLE_AUTHOR = "news-author"
ROLE_VIEWER = "news-viewer"


async def _build_app(user: Any, *, mount_public: bool = False) -> tuple[FastAPI, Any]:
    module = NewsModule()
    app = FastAPI()

    api_router = APIRouter(prefix=module.meta.route_prefix, tags=[module.meta.name])
    view_router = APIRouter(prefix=module.meta.view_prefix, tags=[module.meta.name])
    module.register_routes(api_router, view_router)
    app.include_router(api_router)
    app.include_router(view_router)

    db_state = await make_db_state()

    registry = PermissionRegistry()
    registry.add_group("News", [PERM_VIEW, PERM_EDIT, PERM_PUBLISH])
    registry.map_role(ROLE_EDITOR, [PERM_VIEW, PERM_EDIT, PERM_PUBLISH])
    registry.map_role(ROLE_AUTHOR, [PERM_VIEW, PERM_EDIT])
    registry.map_role(ROLE_VIEWER, [PERM_VIEW])
    app.state.sm = SimpleNamespace(db=db_state, permissions=registry)
    # News' settings are DB-backed, so ``register_settings`` registers the class
    # against the settings module's registry rather than reading the
    # environment. Nothing hydrates it here: these tests want the declared
    # defaults, which is exactly what the container is built from.
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
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

    app.add_middleware(StubAuthMiddleware, user=user)
    # Inertia reads flashed errors off the session on every render, so the
    # public viewer cannot answer at all without this. Added last so it ends up
    # outermost at runtime — Starlette runs the last-added middleware first on
    # the way in — which matches the host's own order.
    app.add_middleware(SessionMiddleware, secret_key="news-tests")

    if mount_public:
        # Most fixtures skip this: the admin API is what they exercise, and
        # ``on_startup`` mounts a router per content locale, which is
        # process-global. The public viewer only exists once it has run, so the
        # tests that are *about* the article's address ask for it.
        await module.on_startup(app)
    return app, db_state


@pytest_asyncio.fixture
async def db_state() -> AsyncIterator[Any]:
    """A bare database with the module's tables, for direct service tests."""
    state = await make_db_state()
    yield state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def db(db_state) -> AsyncIterator[AsyncSession]:
    async with db_state.session_factory() as session:
        yield session


async def _client(user: Any, *, mount_public: bool = False) -> AsyncIterator[AsyncClient]:
    app, state = await _build_app(user, mount_public=mount_public)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        client.db_state = state  # type: ignore[attr-defined]
        yield client
    await state.engine.dispose()


@pytest_asyncio.fixture
async def editor_client() -> AsyncIterator[AsyncClient]:
    """`news.edit` *and* `news.publish` — not WILDCARD."""
    async for client in _client(stub_user((ROLE_EDITOR,))):
        yield client


@pytest_asyncio.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    """Authenticated as `admin`, which resolves to WILDCARD rather than to
    a literal `news.edit` — the case a naive membership test would miss."""
    async for client in _client(stub_user(("admin",))):
        yield client


@pytest_asyncio.fixture
async def author_client() -> AsyncIterator[AsyncClient]:
    """`news.edit`, but not `news.publish`.

    Everything that puts an article in front of readers has to refuse this
    caller, or owning the workflow quietly widened what `news.edit` grants.
    """
    async for client in _client(stub_user((ROLE_AUTHOR,))):
        yield client


@pytest_asyncio.fixture
async def viewer_client() -> AsyncIterator[AsyncClient]:
    """Authenticated but without `news.edit`."""
    async for client in _client(stub_user((ROLE_VIEWER,))):
        yield client


@pytest_asyncio.fixture
async def anon_client() -> AsyncIterator[AsyncClient]:
    """No session at all — what an anonymous reader sees.

    Mounts the public routes, unlike the authenticated fixtures: everything
    this client is used for is on the reader's side of the app.
    """
    async for client in _client(None, mount_public=True):
        yield client


@pytest_asyncio.fixture
async def editor_public_client() -> AsyncIterator[AsyncClient]:
    """An editor, on an app that also mounts the public viewer.

    The one shape neither half gives on its own: a published article whose
    author has kept editing has to be read at the preview *and* at its public
    URL, in the same database, to show that the two are serving different
    versions. Every other fixture has one or the other.
    """
    async for client in _client(stub_user((ROLE_EDITOR,)), mount_public=True):
        yield client


@pytest_asyncio.fixture
async def bilingual_public_client(bilingual) -> AsyncIterator[AsyncClient]:
    """An anonymous reader on a two-language app with its public routes mounted.

    ``on_startup`` is what mounts them — one router per content locale — so a
    test about the address an article serves at has to boot through it rather
    than around it. Depending on ``bilingual`` rather than taking it as a
    second fixture argument is load-bearing: the locales have to be published
    *before* the app is built, or the routers are mounted for one language.
    """
    async for client in _client(None, mount_public=True):
        yield client


