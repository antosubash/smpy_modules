"""Every test runs as the single-tenant host's tenant unless it opts out.

A registered plugin rather than part of ``conftest.py``, which sits on the
repo's 300-line cap — the same reason ``db_fixture`` is one. See the module's
``[tool.pytest.ini_options]``.
"""

from __future__ import annotations

import pytest
from pagebuilder.tenancy import DEFAULT_TENANT
from simple_module_db import tenant_context


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "unbound_tenant: run the test with no tenant bound (the autouse "
        "default-tenant fixture steps aside)",
    )


@pytest.fixture(autouse=True)
def _default_tenant(request: pytest.FixtureRequest):
    """Bind :data:`DEFAULT_TENANT` around the whole test.

    Every pagebuilder table carries ``MultiTenantMixin``, whose column is
    ``NOT NULL`` and stamped from the bound tenant at flush, so a test that
    seeds a row directly through a session needs one — as the routers bind it
    for a request. Synchronous and autouse so it is set up before any async
    fixture: pytest-asyncio runs each async fixture and test in a copy of this
    context, so the binding reaches all of them, and through
    ``httpx.ASGITransport`` every request a test makes.

    ``@pytest.mark.unbound_tenant`` opts a test out, for the ones that are
    about what happens with no tenant bound.
    """
    if request.node.get_closest_marker("unbound_tenant") is not None:
        yield None
        return
    with tenant_context(DEFAULT_TENANT):
        yield DEFAULT_TENANT
