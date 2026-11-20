"""The ``registration`` prop of the public event page (PR 9): the same for everyone and cached, so
it names where to register and never how full the event is."""

from __future__ import annotations

import pytest
from sm_events.calendar.plugins import registry
from sm_events.models import Event
from sm_events.registration.args import occurrence_key
from sqlalchemy import update

from tests.support.providers import KNOWN_TARGET, PROVIDER_ID, install_provider, provider
from tests.support.public import INERTIA, seed_public

KEYS = {"mode", "url", "provider", "target", "occurrence_key", "upcoming"}
FORBIDDEN = ("capacity", "taken", "seats", "email", "name", "address")


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    install_provider(monkeypatch, provider())
    yield
    registry.reset_registry()


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client)


async def put(client, event, **fields):
    async with client.db_state.session_factory() as db:
        await db.execute(update(Event).where(Event.id == event.id).values(**fields))
        await db.commit()


BUILTIN = {
    "registration_mode": "builtin",
    "registration_provider": PROVIDER_ID,
    "registration_target": KNOWN_TARGET,
}


async def page(client, fx, event, query=""):
    got = await client.get(f"/events/{fx.slug(event)}{query}", headers=INERTIA)
    assert got.status_code == 200, got.text[:200]
    return got, got.json()["props"]["registration"]


async def test_none_by_default(public_locales_client, fx):
    _, reg = await page(public_locales_client, fx, fx.one_off)
    assert reg == {
        "mode": "none",
        "url": None,
        "provider": None,
        "target": None,
        "occurrence_key": None,
        "upcoming": [],
    }


async def test_external_is_the_link(public_locales_client, fx):
    await put(
        public_locales_client,
        fx.one_off,
        registration_mode="external",
        registration_url="https://register.example/x",
    )
    _, reg = await page(public_locales_client, fx, fx.one_off)
    assert (reg["mode"], reg["url"]) == ("external", "https://register.example/x")
    assert reg["provider"] is None and reg["target"] is None and reg["occurrence_key"] is None


async def test_props_cache_safe(public_locales_client, fx):
    """Exactly where and which occurrence; nothing about seats, and the validator does not move
    when a seat is taken between two requests."""
    await put(public_locales_client, fx.one_off, **BUILTIN, registration_capacity=5)
    first, reg = await page(public_locales_client, fx, fx.one_off)
    assert set(reg) == KEYS
    assert (reg["mode"], reg["provider"], reg["target"]) == ("builtin", PROVIDER_ID, KNOWN_TARGET)
    assert reg["occurrence_key"] == str(fx.one_off.id) and reg["upcoming"] == []
    assert not any(word in str(first.json()["props"]["registration"]) for word in FORBIDDEN)
    from sm_events.contracts import registration as contract
    from sm_events.core.tenancy import tenant_scope

    with tenant_scope("default"):
        async with public_locales_client.db_state.session_factory() as db:
            got = await contract.admit(
                db,
                tenant_id="default",
                event_id=fx.one_off.id,
                occurrence_key=occurrence_key(str(fx.one_off.id)),
                provider=PROVIDER_ID,
                target=KNOWN_TARGET,
                holder="h1",
                admin=True,
            )
            assert got.admitted
            await db.commit()
    second, _ = await page(public_locales_client, fx, fx.one_off)
    assert second.headers["etag"] == first.headers["etag"]
    assert second.headers["cache-control"] == first.headers["cache-control"]


async def test_series_without_date(public_locales_client, fx):
    """The bare page of a series has no occurrence of its own: a few upcoming dates to choose."""
    await put(public_locales_client, fx.series, **BUILTIN)
    _, reg = await page(public_locales_client, fx, fx.series)
    assert reg["occurrence_key"] is None
    assert 1 <= len(reg["upcoming"]) <= 5
    for item in reg["upcoming"]:
        assert item["url"].startswith(f"/events/{fx.slug(fx.series)}?date=")
        assert item["status"] != "cancelled"
        assert not any(word in str(item) for word in FORBIDDEN)


async def test_series_with_a_date_names_that_occurrence(public_locales_client, fx):
    await put(public_locales_client, fx.series, **BUILTIN)
    _, reg = await page(public_locales_client, fx, fx.series, "?date=2026-03-16")
    assert reg["occurrence_key"] == f"{fx.series.id}:20260316T090000Z" or reg[
        "occurrence_key"
    ].startswith(f"{fx.series.id}:20260316T")
    assert reg["upcoming"] == []


async def test_cancelled_no_panel(public_locales_client, fx):
    await put(public_locales_client, fx.one_off, **BUILTIN, cancelled=True)
    _, reg = await page(public_locales_client, fx, fx.one_off)
    assert reg["mode"] == "none" and reg["target"] is None and reg["occurrence_key"] is None


async def test_a_provider_that_is_gone_shows_no_panel(public_locales_client, fx, monkeypatch):
    install_provider(monkeypatch)  # no provider installed
    await put(public_locales_client, fx.one_off, **BUILTIN)
    _, reg = await page(public_locales_client, fx, fx.one_off)
    assert reg["mode"] == "none"
