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

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

# ``pg_support`` owns the one decision both database fixtures make: in-memory
# SQLite, or the Postgres database ``SM_TEST_DATABASE_URL`` names. It is also
# where "news' tables, plus pagebuilder's where installed" is spelled out.
from pg_support import arm_reset, make_db_state
from sqlalchemy.ext.asyncio import AsyncSession

from tests.support.app import (
    ROLE_AUTHOR,
    ROLE_EDITOR,
    ROLE_VIEWER,
    _client,
)
from tests.support.stub_auth import stub_user

pytest_plugins = ("tests.support.tenant_fixture",)


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
    from news.core import settings as news_settings
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
