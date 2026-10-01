"""Fixtures several suites share, defined once and imported by ``conftest.py``.

Each used to be copy-pasted into every file that wanted it: importing a
fixture by name into a *test* module is what makes ruff read the test
signature that uses it as a redefinition. Importing it into ``conftest.py``
alone does not, and a test module that needs a different body still overrides
the name locally, by ordinary pytest precedence.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sm_records.deps import require_edit, require_manage_types, require_view
from sm_records.models import Base
from sm_records.settings import RecordsSettings

from tests.app_harness import build_app
from tests.i18n_helpers import use_locales


@pytest.fixture
def settings() -> RecordsSettings:
    return RecordsSettings()


@pytest.fixture
async def order_type(make_type, field_def):
    return await make_type(
        "order",
        [field_def("state", "text"), field_def("total", "number"), field_def("name", "text")],
        display_field="name",
    )


@pytest_asyncio.fixture
async def public_client(client):
    """The harness client, with the module's own ``on_startup`` run.

    Not a hand-rolled ``include_router``: mounting the public API from the
    lifespan hook is the arrangement under test (:mod:`sm_records.boot`), and
    a fixture that mounted the router itself would keep passing after
    ``on_startup`` stopped doing it.
    """
    await client.app.state.records_module.on_startup(client.app)
    return client


@pytest_asyncio.fixture
async def bilingual(client):
    use_locales(client, "en", "de")
    return client


@pytest_asyncio.fixture
async def file_db(tmp_path) -> AsyncIterator[Any]:
    """A real SQLite *file* on the default pool — one connection per session,
    exactly as a server has.

    Not ``:memory:``/``StaticPool``: one shared connection makes every session
    in the process a single transaction, so a check-then-act race or a lock
    that is never taken cannot be caught there.
    """
    state = init_db(f"sqlite+aiosqlite:///{tmp_path / 'file.db'}")
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def file_client(tmp_path, file_db) -> AsyncIterator[AsyncClient]:
    """The module's real routers over :func:`file_db`, with the permission
    dependencies overridden.

    Authentication is not what is under test here and the checker the module
    uses is host-dependent (``sm_records.deps``), so the three static
    permissions are overridden rather than simulated — everything below the
    route is the production wiring, including the middleware. ``.app`` is the
    app, for a suite that has to adjust its settings.
    """
    app, _ = await build_app(tmp_path, file_db)
    for dependency in (require_view, require_edit, require_manage_types):
        app.dependency_overrides[dependency.dependency] = lambda: None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        yield client
