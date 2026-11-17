"""Shared fixtures for the events tests.

``_default_tenant``: every events table the ORM writes carries
``MultiTenantMixin``, whose column is ``NOT NULL`` and stamped from the bound
tenant at flush, so a fixture that inserts a row needs one bound.

``_arm_database_reset``: on Postgres it is what makes the *first* database a
test asks for a clean one (see :func:`tests.pg_support.arm_reset`).
"""

from __future__ import annotations

import pytest
from sm_events.core.tenancy import tenant_scope

from tests.pg_support import arm_reset

DEFAULT_TENANT = "default"


@pytest.fixture(autouse=True)
def _default_tenant(request):
    """Every test runs with ``default`` bound - what a single-tenant host binds.
    Synchronous and autouse so it is set up before any async fixture:
    pytest-asyncio runs each async fixture and test in a *copy* of this context,
    so the binding reaches all of them.

    ``@pytest.mark.unbound_tenant`` opts a test out.
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
