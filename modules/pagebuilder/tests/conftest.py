"""Shared fixtures for pagebuilder integration tests.

Each fixture spins up a fully-wired test app: a database from
``pg_support.make_db_state`` backing the ``get_db`` dep (in-memory
aiosqlite unless ``SM_TEST_DATABASE_URL`` names a Postgres one, with
audit listeners attached either way so writes actually commit),
``SessionMiddleware`` so CSRF + session state work,
a minimal Inertia config so the public viewer can render, and a fresh
``MediaService`` rooted at ``tmp_path`` so uploads never escape the
per-test sandbox.

The fixtures wire the module via its own ``register_*`` hooks rather
than re-implementing them; the only test-specific seam is the
``module.settings`` pre-population, which is how production code can
also override settings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from pagebuilder.core.permissions import (
    PERM_APPROVE,
    PERM_EDIT,
    PERM_PUBLISH,
    ROLE_APPROVER,
    ROLE_EDITOR,
)

# ``pg_support`` owns the one decision every database fixture in this suite
# makes: in-memory SQLite, or the Postgres database ``SM_TEST_DATABASE_URL``
# names. See that module.
from pg_support import arm_reset

from tests.support.app import _client_fixture


@pytest.fixture(autouse=True)
def _arm_database_reset():
    """Every test starts from an empty database.

    A no-op on SQLite, where each test builds its own ``:memory:`` one and
    there is nothing to empty. On Postgres it is what makes the *first*
    database a test asks for a clean one — several fixtures here build two
    (``authed_client`` plus ``db``, say), which are independent databases on
    SQLite and two windows onto one database on Postgres. See
    ``tests/pg_support.py`` at the repo root.
    """
    arm_reset()
    yield


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
        tmp_path, requires_auth=True, csrf_protect=True, inject_user=True, layout=True
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

pytest_plugins = (
    "tests.support.db_fixture",
    "tests.support.locale_fixture",
    "tests.support.snapshot_fixture",
    "tests.support.tenant_fixture",
)
