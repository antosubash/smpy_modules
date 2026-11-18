"""What a public page says does not depend on who asks, and names no event's id."""

from __future__ import annotations

import json
import re

import pytest
from sm_events.web.endpoints.public import _urls

from tests.support.app import as_user
from tests.support.calendars import PublicFixture
from tests.support.public import INERTIA, seed_public
from tests.web.public.leaks import LOCALES, _api_url

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@pytest.fixture
async def fx(public_locales_client) -> PublicFixture:
    return await seed_public(public_locales_client)


def _public_addresses(fx: PublicFixture, locale: str) -> list[str]:
    pages = [
        fx.one_off,
        fx.series,
        fx.conf,
        fx.talk,
        fx.orphan,
    ]  # a parent with a draft child, a child with a draft parent
    return [
        *[_urls.event_path(fx.slug(e, locale), locale) for e in pages],
        *[_urls.event_ics_path(fx.slug(e, locale), locale) for e in pages],
        _urls.index_path(locale),
        _urls.calendar_path(fx.pub.slug, locale),
        _urls.calendar_ics_path(fx.pub.slug, locale),
        _urls.calendar_ics_path(None, locale),
        _urls.sitemap_path(),
        _api_url(locale),
    ]


async def test_a_signed_in_manager_sees_the_anonymous_bytes_on_public_pages(
    public_locales_client, fx
):
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    for locale in LOCALES:
        for url in _public_addresses(fx, locale):
            anon = await public_locales_client.get(url, headers=INERTIA)
            signed = await public_locales_client.get(url, headers=INERTIA | manager)
            assert anon.status_code == signed.status_code == 200, url
            if "x-inertia" in anon.headers:
                assert signed.json()["props"] == anon.json()["props"], url
            assert signed.content == anon.content, url
            assert signed.headers.get("content-type") == anon.headers.get("content-type"), url


async def test_no_public_json_names_an_event_id(public_locales_client, fx):
    """Event ids stay out of the page props, the sub-events' keys and the occurrences API (the
    ids of public calendars and categories are the grid's filter inputs, so they stay)."""
    ids = {str(e.id) for e in [*fx.public_events, *fx.hidden.values()]}
    public_ids = {str(fx.pub.id), str(fx.public_cat.id)}
    seen = 0
    for locale in LOCALES:
        for url in _public_addresses(fx, locale):
            if url.endswith((".ics", ".xml")):
                continue
            got = await public_locales_client.get(url, headers=INERTIA)
            text = json.dumps(got.json())
            seen += 1
            assert not any(i in text for i in ids), url
            assert set(UUID.findall(text)) <= public_ids, url
    assert seen == 16
