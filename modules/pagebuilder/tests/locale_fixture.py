"""Fixtures for a site that publishes in more than one language.

A registered plugin rather than part of ``conftest.py``, which sits on the
repo's 300-line cap — the same reason ``db_fixture`` is one. See the module's
``[tool.pytest.ini_options]``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from conftest import _client_fixture
from httpx import AsyncClient
from pagebuilder import locales

CONTENT_LOCALES = ("en", "de")
"""What the multilingual fixtures configure. English stays the default, so it
keeps serving at the unprefixed URL and every single-language test is
unaffected."""


@pytest.fixture(autouse=True)
def _no_leaked_locales():
    """The resolved settings are published process-wide.

    ``Page.locale``'s column default reads them, so a multilingual test that
    left them behind would make the *next* test's pages come out in whatever
    language it had configured — an order-dependent failure with no visible
    cause. Reset on the way in as well as out, because a test that fails
    mid-way still has to leave the process clean.
    """
    locales.reset()
    yield
    locales.reset()


@pytest.fixture
async def bilingual_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Admin client on a site publishing in English (default) and German."""
    async for c in _client_fixture(
        tmp_path,
        requires_auth=True,
        csrf_protect=False,
        inject_user=True,
        settings={"content_locales": CONTENT_LOCALES, "default_content_locale": "en"},
    ):
        yield c
