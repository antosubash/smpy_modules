"""The event page: cancelled and rescheduled dates, links, the head, validators and caching."""

from __future__ import annotations

import json
import re

import pytest
from sm_events.models import Calendar, Event, EventText
from sqlalchemy import select

from tests.support.app import as_user
from tests.support.calendars import seed_event
from tests.support.public import INERTIA, seed_public
from tests.web.public.conftest import NOW

EVIL = "</script><script>alert(1)</script>"


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client)


@pytest.fixture
async def fx_partial(public_locales_client):
    return await seed_public(public_locales_client, german=False)


async def get(client, path, **headers):
    return await client.get(path, headers=INERTIA | headers)


def props(response) -> dict:
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["component"] == "Events/PublicEvent"
    return body["props"]


async def mutate(client, fn):
    async with client.db_state.session_factory() as session:
        out = await fn(session)
        await session.commit()
        return out


async def text_of(db, event_id, locale="en") -> EventText:
    stmt = select(EventText).where(EventText.event_id == event_id, EventText.locale == locale)
    return (await db.execute(stmt)).scalar_one()


async def test_head_and_json_ld_cannot_break_out(public_locales_client, fx):
    separator = chr(0x2028)

    async def evil(db):
        text = await text_of(db, fx.one_off.id)
        text.title = EVIL + separator
        text.summary = EVIL

    await mutate(public_locales_client, evil)
    html = (await public_locales_client.get(f"/events/{fx.slug(fx.one_off)}")).text
    assert "<script>alert" not in html
    assert html.count("<script") == 2 and html.count("</script>") == 2  # the shell's and JSON-LD
    ld = re.search(
        r'<script type="application/ld\+json" data-inertia="json-ld">(.*?)</script>', html, re.S
    ).group(1)
    assert json.loads(ld)["name"] == EVIL + separator
    assert separator not in ld  # the JS line separator is an escape inside the script
    assert "&lt;/script&gt;" in html  # the title in <title> and og: is escaped text


async def test_head_tags(public_locales_client, fx):
    slug = fx.slug(fx.one_off)
    html = (await public_locales_client.get(f"/events/{slug}")).text
    assert f"<title>{slug.title()}</title>" in html
    assert (
        f'<link rel="canonical" data-inertia="canonical" href="http://test/events/{slug}">' in html
    )
    assert '<meta property="og:type" data-inertia="og:type" content="website">' in html
    assert 'hreflang="de"' in html and 'hreflang="x-default"' in html
    assert '<html lang="en"' in html
    de = (await public_locales_client.get(f"/de/events/{fx.slug(fx.one_off, 'de')}")).text
    assert '<html lang="de"' in de


async def test_etag_changes_with_child_and_calendar(public_locales_client, fx):
    path = f"/events/{fx.slug(fx.conf)}"
    tag = (await get(public_locales_client, path)).headers["etag"]

    async def add_child(db):
        cal = await db.get(Calendar, fx.pub.id)
        await seed_event(db, cal, slug="second-talk", status="published", parent_id=fx.conf.id)

    await mutate(public_locales_client, add_child)
    after_child = await get(public_locales_client, path, **{"If-None-Match": tag})
    assert after_child.status_code == 200 and after_child.headers["etag"] != tag

    async def rename(db):
        (await db.get(Calendar, fx.pub.id)).name = "Renamed calendar"

    await mutate(public_locales_client, rename)
    after_cal = await get(
        public_locales_client, path, **{"If-None-Match": after_child.headers["etag"]}
    )
    assert after_cal.status_code == 200 and after_cal.headers["etag"] != after_child.headers["etag"]
    assert props(after_cal)["calendar"]["name"] == "Renamed calendar"


async def test_html_and_json_never_share_an_etag(public_locales_client, fx):
    path = f"/events/{fx.slug(fx.one_off)}"
    assert (await public_locales_client.get(path)).headers["etag"] != (
        await get(public_locales_client, path)
    ).headers["etag"]


async def test_signed_in_gets_no_validator_and_the_same_props(public_locales_client, fx):
    path = f"/events/{fx.slug(fx.one_off)}"
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    anon, signed = (
        await get(public_locales_client, path),
        await get(public_locales_client, path, **manager),
    )
    assert signed.headers["cache-control"] == "private, no-store" and "etag" not in signed.headers
    assert props(signed) == props(anon)


@pytest.mark.unbound_tenant
async def test_cache_headers(public_locales_client, fx):
    got = await get(public_locales_client, f"/events/{fx.slug(fx.one_off)}")
    assert got.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=60"


async def test_a_public_event_is_not_the_404(public_locales_client, fx):
    """The control for the leak table: its 404s mean something because this is a 200."""
    for event in fx.public_events:
        got = await get(public_locales_client, f"/events/{fx.slug(event)}")
        assert got.status_code == 200, fx.slug(event)


async def test_malformed_slugs_are_a_miss(public_locales_client, fx):
    for path in ("/events/%00", "/events/a%20b", "/events/" + "a" * 300, "/events/UPPER"):
        got = await get(public_locales_client, path)
        assert got.status_code == 404 and got.json()["component"] == "Events/PublicNotFound", path


@pytest.mark.unbound_tenant
async def test_other_tenant(public_multi_client):
    mine = await seed_public(public_multi_client, tag="-a", tenant="a")
    theirs = await seed_public(public_multi_client, tag="-b", tenant="b")
    as_a = INERTIA | {"X-Test-Tenant": "a"}
    ok = await public_multi_client.get(f"/events/{mine.slug(mine.one_off)}", headers=as_a)
    assert ok.status_code == 200 and ok.headers["cache-control"].startswith("private")
    for event in theirs.public_events:
        got = await public_multi_client.get(f"/events/{theirs.slug(event)}", headers=as_a)
        assert got.status_code == 404
    nobody = await public_multi_client.get(f"/events/{mine.slug(mine.one_off)}", headers=INERTIA)
    assert nobody.status_code == 404
    assert NOW  # the fixed clock is shared with the other public tests


async def test_cancelled_event(public_locales_client, fx):
    async def cancel(db):
        row = await db.get(Event, fx.one_off.id)
        row.cancelled, row.registration_url = True, "https://register.example/x"

    await mutate(public_locales_client, cancel)
    got = await get(public_locales_client, f"/events/{fx.slug(fx.one_off)}")
    p = props(got)
    assert p["cancelled"] is True and p["registration_url"] is None and p["index_in_search"] is True
    assert p["json_ld"]["eventStatus"].endswith("EventCancelled")
    html = (await public_locales_client.get(f"/events/{fx.slug(fx.one_off)}")).text
    assert "robots" not in html


async def test_registration_link_when_not_cancelled(public_locales_client, fx):
    async def link(db):
        (await db.get(Event, fx.one_off.id)).registration_url = "https://register.example/x"

    await mutate(public_locales_client, link)
    assert (
        props(await get(public_locales_client, f"/events/{fx.slug(fx.one_off)}"))[
            "registration_url"
        ]
        == "https://register.example/x"
    )


async def test_unsafe_urls_are_dropped(public_locales_client, fx):
    async def bad(db):
        row = await db.get(Event, fx.one_off.id)
        row.registration_url, row.image, row.online_url = (
            "javascript:alert(1)",
            "data:text/html,x",
            "ftp://x",
        )

    await mutate(public_locales_client, bad)
    p = props(await get(public_locales_client, f"/events/{fx.slug(fx.one_off)}"))
    assert p["registration_url"] is None and p["image"] is None and p["place"]["online_url"] is None


async def test_noindex_text(public_locales_client, fx):
    async def hide(db):
        (await text_of(db, fx.one_off.id)).noindex = True

    await mutate(public_locales_client, hide)
    path = f"/events/{fx.slug(fx.one_off)}"
    assert props(await get(public_locales_client, path))["index_in_search"] is False
    assert (
        '<meta name="robots" data-inertia="robots" content="noindex,nofollow">'
        in (await public_locales_client.get(path)).text
    )


async def test_description_tree(public_locales_client, fx):
    async def stored(db):
        (
            await text_of(db, fx.one_off.id)
        ).description = "<p onclick=x>Hi <script>bad()</script></p>"

    await mutate(public_locales_client, stored)
    p = props(await get(public_locales_client, f"/events/{fx.slug(fx.one_off)}"))
    assert p["description_tree"] == [{"t": "p", "c": ["Hi "]}]
