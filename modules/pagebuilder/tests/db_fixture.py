"""A bare database session fixture, re-exported from ``conftest``.

Kept out of ``conftest.py`` only because that file sits exactly on the repo's
300-line cap; it belongs to the same fixture set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pagebuilder.models import Base
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy.pool import StaticPool


@pytest.fixture
async def db() -> AsyncIterator[Any]:
    """A session against an in-memory database with pagebuilder's tables.

    For service-level tests that have nothing to say about HTTP — the retention
    sweep runs from the scheduler tick, not from a request, so driving it
    through a client would mean testing a route that does not exist.

    ``StaticPool`` so every session in the test sees the same ``:memory:``
    instance, and ``register_listeners`` so the audit hook behaves as it does in
    the app.
    """
    state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    register_listeners(state)
    async with state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with state.session_factory() as session:
        yield session
    await state.engine.dispose()
