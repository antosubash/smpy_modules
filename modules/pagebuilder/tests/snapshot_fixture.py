"""Fixtures for the snapshot layer, registered as a plugin.

Kept out of ``conftest.py`` for the same reason as ``db_fixture``: that file
sits on the repo's 300-line cap. Registered via ``-p snapshot_fixture`` in
``pyproject.toml``.

Two fixtures live here. ``snapshot_db`` is a bare session + settings pair,
because the snapshot layer talks to the ORM directly and does not need the full
ASGI harness. ``publisher_client`` is an authenticated client holding *publish
but not approve* — the only way to test the approval gate, since two client
fixtures in one test would get two separate in-memory databases.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import _client_fixture
from httpx import AsyncClient
from pagebuilder import locales
from pagebuilder.permissions import PERM_EDIT, PERM_PUBLISH, ROLE_PUBLISHER
from pagebuilder.settings import PagebuilderSettings
from pg_support import make_db_state


@pytest.fixture
async def publisher_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Stub user holding edit + publish, but deliberately not approve."""
    async for client in _client_fixture(
        tmp_path,
        requires_auth=True,
        csrf_protect=False,
        inject_user=True,
        user_roles=(ROLE_PUBLISHER,),
        role_map={ROLE_PUBLISHER: [PERM_EDIT, PERM_PUBLISH]},
    ):
        yield client


@pytest.fixture
async def snapshot_db(tmp_path) -> AsyncIterator[Any]:
    """An empty pagebuilder schema plus settings rooted in ``tmp_path``.

    Same ``make_db_state`` as the app harness, for the same reasons — one
    connection on SQLite so every ``async with`` sees the same ``:memory:``
    database instead of a fresh one, and the same ``SM_TEST_DATABASE_URL``
    opt-in onto Postgres.
    """
    db_state = await make_db_state()
    settings = PagebuilderSettings(
        media_root=tmp_path / "media",
        snapshot_root=tmp_path / "snapshots",
    )
    async with db_state.session_factory() as session:
        yield SimpleNamespace(session=session, settings=settings)
    await db_state.engine.dispose()


@pytest.fixture
async def bilingual_snapshot_db(tmp_path) -> AsyncIterator[Any]:
    """``snapshot_db`` on a site publishing in English (default) and German.

    The locales are *published* with ``locales.use``, not merely set on the
    settings object: ``Page.locale``'s column default and the snapshot layer's
    own readers both go through the process-wide accessor, so a fixture that
    only built the settings would hand out pages in the default locale and
    quietly test the monolingual path instead. ``locale_fixture``'s autouse
    reset clears it again after the test.
    """
    db_state = await make_db_state()
    settings = PagebuilderSettings(
        media_root=tmp_path / "media",
        snapshot_root=tmp_path / "snapshots",
        content_locales=("en", "de"),
        default_content_locale="en",
    )
    locales.use(settings)
    async with db_state.session_factory() as session:
        yield SimpleNamespace(session=session, settings=settings)
    await db_state.engine.dispose()
