"""``/events/sitemap.xml``: every public indexable event, bounded, escaped, cached."""

from __future__ import annotations

from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import pytest
from sm_events.core import constants
from sm_events.models import Event, EventText
from sm_events.web.endpoints.public import _urls

from tests.support.app import as_user
from tests.support.public import seed_public, tenant_header

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
PATH = "/events/sitemap.xml"


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client)


def urls(response) -> list[tuple[str, str | None]]:
    root = ET.fromstring(response.content)  # noqa: S314 - our own output
    out = []
    for node in root.findall("s:url", NS):
        lastmod = node.find("s:lastmod", NS)
        out.append((node.find("s:loc", NS).text, None if lastmod is None else lastmod.text))
    return out


def locs(response) -> list[str]:
    return [loc for loc, _ in urls(response)]


async def mutate(client, fn):
    async with client.db_state.session_factory() as session:
        out = await fn(session)
        await session.commit()
        return out


async def test_lists_indexes_calendars_events(public_locales_client, fx):
    got = await public_locales_client.get(PATH)
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/xml; charset=utf-8"
    found = locs(got)
    assert "http://test/events/" in found and "http://test/de/events/" in found
    for locale in ("en", "de"):
        assert f"http://test{_urls.calendar_path(fx.pub.slug, locale)}" in found
    for event in fx.public_events:
        assert f"http://test{_urls.event_path(fx.slug(event), 'en')}" in found, fx.slug(event)
    for event in (fx.one_off, fx.series):  # the two with a German text at their own address
        assert f"http://test{_urls.event_path(fx.slug(event, 'de'), 'de')}" in found
    assert len(found) == len(set(found))


async def test_every_event_has_a_lastmod(public_locales_client, fx):
    dated = [
        (loc, mod) for loc, mod in urls(await public_locales_client.get(PATH)) if "/c/" not in loc
    ]
    events = [(loc, mod) for loc, mod in dated if loc.rstrip("/").split("/")[-1] != "events"]
    assert events and all(mod and len(mod) == 10 for _, mod in events)  # YYYY-MM-DD


async def test_hidden_rows_are_absent(public_locales_client, fx):
    text = (await public_locales_client.get(PATH)).text
    for event in fx.hidden.values():
        for locale in ("en", "de"):
            slug = fx.slugs.get(f"{event.id}:{locale}")
            assert slug is None or slug not in text
    for calendar in (fx.internal, fx.private, fx.gone):
        assert f"/c/{calendar.slug}" not in text


async def test_noindex_excluded(public_locales_client, fx):
    async def hide(db):
        from sqlalchemy import select

        stmt = select(EventText).where(
            EventText.event_id == fx.one_off.id, EventText.locale == "en"
        )
        (await db.execute(stmt)).scalar_one().noindex = True

    await mutate(public_locales_client, hide)
    found = locs(await public_locales_client.get(PATH))
    assert f"http://test/events/{fx.slug(fx.one_off)}" not in found
    assert f"http://test/de/events/{fx.slug(fx.one_off, 'de')}" in found  # the German text is not


async def test_no_date_urls(public_locales_client, fx):
    assert not [loc for loc in locs(await public_locales_client.get(PATH)) if "?" in loc]


async def test_newest_first_and_bounded(public_locales_client, fx, monkeypatch):
    async def touch(db):
        for n, event in enumerate(fx.public_events):
            row = await db.get(Event, event.id)
            row.updated_at = datetime(2026, 1 + n, 1, tzinfo=UTC)

    await mutate(public_locales_client, touch)
    got = await public_locales_client.get(PATH)
    events = [
        (loc, mod)
        for loc, mod in urls(got)
        if mod and "/c/" not in loc and not loc.endswith("/events/")
    ]
    mods = [mod for _, mod in events]
    assert mods == sorted(mods, reverse=True)
    monkeypatch.setattr(constants, "SITEMAP_MAX_URLS", 5)
    capped = await public_locales_client.get(PATH)
    assert len(urls(capped)) == 5


async def test_xml_is_escaped(public_locales_client, fx):
    """Nothing is concatenated into the XML: even an origin with markup characters (a
    misconfigured ``public_base_url``) leaves a well-formed document."""
    public_locales_client.app.state.sm.settings.public_base_url = "https://example.org/a&b<c>"
    got = await public_locales_client.get(PATH)
    root = ET.fromstring(got.content)  # noqa: S314 - our own output; well-formed
    first = root.find("s:url/s:loc", NS).text
    assert first.startswith("https://example.org/a&b<c>/events/")
    assert b"<c>" not in got.content and b"a&amp;b&lt;c&gt;" in got.content
    assert got.content.startswith(b"<?xml version='1.0' encoding='utf-8'?>")


async def test_only_default_prefix(public_locales_client, fx):
    assert (await public_locales_client.get("/de/events/sitemap.xml")).status_code == 404


async def test_not_listed_languages_are_not_served(public_locales_client, fx):
    """A text in a language the site no longer publishes in has no page, so no entry."""

    async def other(db):
        db.add(EventText(event_id=fx.one_off.id, locale="fr", slug="bonjour", title="Bonjour"))

    await mutate(public_locales_client, other)
    assert "bonjour" not in (await public_locales_client.get(PATH)).text


@pytest.mark.unbound_tenant
async def test_cache_and_etag(public_locales_client, fx):
    got = await public_locales_client.get(PATH)
    assert got.headers["cache-control"] == "public, max-age=300"
    again = await public_locales_client.get(PATH, headers={"If-None-Match": got.headers["etag"]})
    assert again.status_code == 304 and again.headers["etag"] == got.headers["etag"]
    assert "content-security-policy" not in again.headers
    head = await public_locales_client.head(PATH)
    assert head.content == b"" and head.headers["content-length"] == str(len(got.content))


async def test_a_signed_in_manager_gets_the_same_sitemap(public_locales_client, fx):
    anon = await public_locales_client.get(PATH)
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    assert (await public_locales_client.get(PATH, headers=manager)).content == anon.content


@pytest.mark.unbound_tenant
async def test_tenant_scoped(public_multi_client):
    mine = await seed_public(public_multi_client, tag="-a", tenant="a")
    theirs = await seed_public(public_multi_client, tag="-b", tenant="b")
    got = await public_multi_client.get(PATH, headers=tenant_header("a"))
    assert mine.slug(mine.one_off) in got.text and theirs.slug(theirs.one_off) not in got.text
    assert got.headers["cache-control"].startswith("private") and "Cookie" in got.headers["vary"]
    nobody = await public_multi_client.get(PATH)
    assert nobody.status_code == 404 and nobody.headers["cache-control"] == "no-store"
