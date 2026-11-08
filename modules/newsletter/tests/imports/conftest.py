"""The default fixture of the import tests: an app on its own file database with list ``news``."""

from __future__ import annotations

import pytest_asyncio

from tests.imports.world import FIELDS
from tests.support.app import build_app
from tests.support.records_seed import seed_list


@pytest_asyncio.fixture
async def state(tmp_path):
    _app, st = await build_app(file=tmp_path / "import.db")
    await seed_list(st, "default", fields=FIELDS)
    yield st
    await st.engine.dispose()
