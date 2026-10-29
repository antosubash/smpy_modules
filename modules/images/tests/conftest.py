"""Shared fixtures for the images tests.

Two things are load-bearing and easy to drop when extending this file:

``_default_tenant``: every images table the ORM writes carries
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
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope
from sqlalchemy.ext.asyncio import AsyncSession

from tests.ai_support import ai  # noqa: F401 - the AI step tests' fixture
from tests.app_harness import (  # noqa: F401 - re-exported as fixtures/helpers
    ADMIN_PERMS,
    as_user,
    client,
    images_app,
    storage,
)
from tests.billing_support import _billing_off, gauge, hooks  # noqa: F401 - billing off unless asked
from tests.direct_support import small_parts  # noqa: F401 - two parts per test image
from tests.fetch_support import inner, resolver  # noqa: F401 - the safe-fetch tests' fixtures
from tests.group_support import file_pipe  # noqa: F401 - the group-run tests' fixture
from tests.import_support import imp  # noqa: F401 - the import tests' fixture
from tests.isolation_support import two_tenants  # noqa: F401 - the tenancy matrix's fixture
from tests.pg_support import arm_reset, make_db_state
from tests.pipeline_api_support import world  # noqa: F401 - the pipeline API tests' fixture
from tests.pipeline_support import pipe  # noqa: F401 - the pipeline tests' fixture
from tests.prompts_support import prompts_world  # noqa: F401 - the prompt route tests' fixture
from tests.upload_support import uploads  # noqa: F401 - the upload tests' client


@pytest.fixture(autouse=True)
def _default_tenant(request):
    """Every test runs inside ``tenant_scope(DEFAULT_TENANT)`` - what a
    single-tenant host binds. Synchronous and autouse so it is set up before any
    async fixture: pytest-asyncio runs each async fixture and test in a *copy*
    of this context, so the binding reaches all of them.

    ``@pytest.mark.unbound_tenant`` opts a test out.
    """
    if request.node.get_closest_marker("unbound_tenant") is not None:
        yield None
        return
    with tenant_scope(DEFAULT_TENANT) as tenant:
        yield tenant


@pytest.fixture(autouse=True)
def _reset_intent_factory(monkeypatch):
    """``use_session_factory`` sets a process-wide default; a test that sets it
    must not hand its (disposed) factory to the next one."""
    from sm_images import intents

    monkeypatch.setattr(intents, "_default_factory", None)


@pytest.fixture(autouse=True)
def _reset_pipeline_runtime(monkeypatch):
    """The web runtime is process-wide too (``on_startup`` sets it)."""
    from sm_images.pipeline import runtime

    monkeypatch.setattr(runtime, "_runtime", None)


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
