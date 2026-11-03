"""Shared fixtures for the newsletter tests.

``_default_tenant``: every newsletter table the ORM writes carries
``MultiTenantMixin``, whose column is ``NOT NULL`` and stamped from the bound
tenant at flush, so a fixture that inserts a row needs one bound.

``_arm_database_reset``: on Postgres it is what makes the *first* database a
test asks for a clean one (see :func:`tests.pg_support.arm_reset`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sm_newsletter.core.tenancy import tenant_scope
from sqlalchemy.ext.asyncio import AsyncSession

from tests.pg_support import arm_reset, make_db_state

DEFAULT_TENANT = "default"


@pytest.fixture(autouse=True)
def _default_tenant(request):
    """Every test runs with ``default`` bound - what a single-tenant host binds.
    Synchronous and autouse so it is set up before any async fixture:
    pytest-asyncio runs each async fixture and test in a *copy* of this context,
    so the binding reaches all of them.

    ``@pytest.mark.unbound_tenant`` opts a test out. Bound with the module's own
    ``tenant_scope``, as its entry points do.
    """
    if request.node.get_closest_marker("unbound_tenant") is not None:
        yield None
        return
    with tenant_scope(DEFAULT_TENANT):
        yield DEFAULT_TENANT


@pytest.fixture(autouse=True)
def _arm_database_reset():
    """Every test starts from an empty database (a no-op on SQLite)."""
    arm_reset()
    yield


@pytest_asyncio.fixture
async def db_state() -> AsyncIterator[Any]:
    """In-memory SQLite by default; Postgres when ``SM_TEST_DATABASE_URL`` says so."""
    state = await make_db_state()
    yield state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def db(db_state) -> AsyncIterator[AsyncSession]:
    async with db_state.session_factory() as session:
        yield session
