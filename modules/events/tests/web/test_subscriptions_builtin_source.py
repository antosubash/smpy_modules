"""The ``subscriptions`` source is built in: never listed, never stored on a calendar."""

from __future__ import annotations

import pytest
from sm_events.calendar.plugins import registry

from tests.support.calendars import BASE, OWNER, make
from tests.support.sources import FakeSource, install
from tests.web.test_extensions_api import SOURCES, put


@pytest.fixture(autouse=True)
def plugins(monkeypatch):
    install(monkeypatch, FakeSource("acme:plain", public=True))
    yield
    registry.reset_registry()


async def test_builtin_subscriptions_not_listed(client):
    got = await client.get(SOURCES, headers=OWNER)
    assert "subscriptions" not in [r["id"] for r in got.json()]


async def test_put_subscriptions_entry_refused(client):
    cid = (await make(client))["id"]
    got = await put(client, cid, [{"id": "subscriptions", "settings": {}}])
    assert got.status_code == 422
    assert got.json()["code"] == "builtin_source"
    stored = (await client.get(f"{BASE}/{cid}", headers=OWNER)).json()
    assert "subscriptions" not in str(stored.get("sources"))
