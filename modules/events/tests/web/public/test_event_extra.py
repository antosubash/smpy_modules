"""A plugin type's ``extra`` on the public site: only its declared public fields, as text."""

from __future__ import annotations

import pytest
from sm_events.calendar import registry
from sm_events.models import Event
from sqlalchemy import select

from tests.support.public import INERTIA, seed_public
from tests.support.sources import install_talk

SECRET = "room-SECRET-42"
EXTRA = {"speaker": "Ada <b>Lovelace</b>", "room": SECRET, "level": "advanced"}


@pytest.fixture(autouse=True)
def talk(monkeypatch):
    install_talk(monkeypatch)
    yield
    registry.reset_registry()


@pytest.fixture
async def fx(public_locales_client):
    fx = await seed_public(public_locales_client)

    async def go(db):
        row = (await db.execute(select(Event).where(Event.id == fx.one_off.id))).scalar_one()
        row.type, row.extra = "acme:talk", EXTRA

    async with public_locales_client.db_state.session_factory() as s:
        from sm_events.core.tenancy import tenant_scope

        with tenant_scope("default"):
            await go(s)
            await s.commit()
    return fx


def page_url(fx, locale="en"):
    from sm_events.web.endpoints.public import _urls

    return _urls.event_path(fx.slug(fx.one_off, locale), locale)


async def test_public_props_only_public_fields(public_locales_client, fx):
    got = await public_locales_client.get(page_url(fx), headers=INERTIA)
    props = got.json()["props"]
    assert props["type"] == "acme:talk"
    assert props["public_extra"] == {"speaker": "Ada <b>Lovelace</b>"}
    assert SECRET not in got.text and "advanced" not in got.text
    assert "extra" not in props


async def test_secret_absent_from_html_data_page_and_every_surface(public_locales_client, fx):
    from sm_events.web.endpoints.public import _urls

    urls = [
        page_url(fx),
        page_url(fx, "de"),
        _urls.event_ics_path(fx.slug(fx.one_off, "en"), "en"),
        _urls.calendar_ics_path(None, "en"),
        _urls.calendar_ics_path(fx.pub.slug, "en"),
        _urls.index_path("en"),
        _urls.sitemap_path(),
        f"{_urls.api_path()}?start=2026-01-01T00:00:00Z&end=2026-12-31T00:00:00Z",
    ]
    for url in urls:
        for headers in (INERTIA, {}):
            got = await public_locales_client.get(url, headers=headers)
            assert SECRET not in got.text, (url, headers)
            assert "extra" not in got.text.replace("public_extra", ""), (url, headers)


async def test_jsonld_carries_no_extra(public_locales_client, fx):
    got = await public_locales_client.get(page_url(fx), headers=INERTIA)
    assert "Lovelace" not in str(got.json()["props"]["json_ld"])  # not even the public field


async def test_uninstalled_type_public_extra_empty(public_locales_client, fx):
    registry.reset_registry()
    from sm_events.calendar import extensions

    extensions._BUILTIN_LOADERS[:] = extensions._BUILTIN_LOADERS[:1]
    got = await public_locales_client.get(page_url(fx), headers=INERTIA)
    props = got.json()["props"]
    assert props["public_extra"] == {} and props["type"] == "event"
    assert SECRET not in got.text and "Lovelace" not in got.text
