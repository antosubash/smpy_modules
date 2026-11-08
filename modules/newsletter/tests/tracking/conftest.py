"""The ``state`` fixture the tracking tests share: a file-database app, so the
race and lock-order tests get one connection per session."""

from __future__ import annotations

import pytest

from tests.support.sending import make_app


@pytest.fixture
async def state(tmp_path):
    _, db_state, _ = await make_app(file=tmp_path / "tracking.db")
    yield db_state
    await db_state.engine.dispose()
