"""Session + settings fixture for the snapshot layer, registered as a plugin.

Kept out of ``conftest.py`` for the same reason as ``db_fixture``: that file
sits on the repo's 300-line cap. Registered via ``-p snapshot_fixture`` in
``pyproject.toml``.

The snapshot layer talks to the ORM directly, so its tests want a session and a
settings object rather than the full ASGI harness the API tests build.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from pagebuilder.models import Base
from pagebuilder.settings import PagebuilderSettings
from simple_module_db.listeners import register_listeners
from simple_module_db.session import init_db
from sqlalchemy.pool import StaticPool


@pytest.fixture
async def snapshot_db(tmp_path) -> AsyncIterator[Any]:
    """An empty pagebuilder schema plus settings rooted in ``tmp_path``.

    Same ``StaticPool`` reasoning as the app harness: one connection, so every
    ``async with`` sees the same ``:memory:`` database instead of a fresh one.
    """
    db_state = init_db("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    register_listeners(db_state)
    async with db_state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    settings = PagebuilderSettings(
        media_root=tmp_path / "media",
        snapshot_root=tmp_path / "snapshots",
    )
    async with db_state.session_factory() as session:
        yield SimpleNamespace(session=session, settings=settings)
    await db_state.engine.dispose()
