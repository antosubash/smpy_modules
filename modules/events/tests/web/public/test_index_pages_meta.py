"""The index pages' cache, validators and site title."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_events.models import Calendar
from sm_events.web.endpoints.public import _urls

from tests.support.app import as_user
from tests.support.calendars import seed_event
from tests.support.public import INERTIA, seed_public
from tests.web.public.conftest import NOW

IDX = "/events/"


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client)


@pytest.fixture
async def fx_partial(public_locales_client):
    """German on ``one_off`` and ``series`` only: ``conf`` has to fall back."""
    return await seed_public(public_locales_client, german=False)


def props(response) -> dict:
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["component"] == "Events/PublicIndex"
    return body["props"]


def flat(p: dict) -> list[dict]:
    return [item for group in p["groups"] for item in group["items"]]


async def get(client, path, **headers):
    return await client.get(path, headers=INERTIA | headers)


@pytest.mark.unbound_tenant
async def test_cache_page_kinds(public_locales_client, fx):
    got = await get(public_locales_client, IDX)
    assert got.headers["cache-control"] == "public, max-age=60"
    assert {"X-Inertia", "Cookie", "Accept-Language"} <= {
        v.strip() for v in got.headers["vary"].split(",")
    }
    tag = got.headers["etag"]
    again = await get(public_locales_client, IDX, **{"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == tag
    signed = await get(public_locales_client, IDX, **as_user("u", "events.view"))
    assert signed.headers["cache-control"] == "private, no-store" and "etag" not in signed.headers
    html = await public_locales_client.get(IDX)
    assert html.headers["etag"] != tag  # HTML and Inertia JSON never share a validator


async def test_etag_changes_with_the_list(public_locales_client, fx):
    tag = (await get(public_locales_client, IDX)).headers["etag"]
    async with public_locales_client.db_state.session_factory() as db:
        cal = await db.get(Calendar, fx.pub.id)
        await seed_event(
            db, cal, slug="fresh", status="published", starts_at=NOW + timedelta(days=3)
        )
        await db.commit()
    got = await get(public_locales_client, IDX, **{"If-None-Match": tag})
    assert got.status_code == 200 and got.headers["etag"] != tag


async def test_the_site_title_names_the_index_and_the_feed(public_locales_client, fx):
    public_locales_client.app.state.sm_events.settings.public_title = "  What's   on\n here "
    p = props(await get(public_locales_client, IDX))
    assert p["title"] == "What's on here"
    html = (await public_locales_client.get(IDX)).text
    assert "<title>What&#x27;s on here</title>" in html
    feed = await public_locales_client.get(_urls.calendar_ics_path(None, "en"))
    assert b"X-WR-CALNAME:What's on here" in feed.content
    # a calendar's own page and feed are named for the calendar
    assert (
        props(await get(public_locales_client, f"/events/c/{fx.pub.slug}"))["title"] == fx.pub.name
    )
    one = await public_locales_client.get(_urls.calendar_ics_path(fx.pub.slug, "en"))
    assert f"X-WR-CALNAME:{fx.pub.name}".encode() in one.content


async def test_a_blank_site_title_is_the_module_name(public_locales_client, fx):
    public_locales_client.app.state.sm_events.settings.public_title = "   "
    assert props(await get(public_locales_client, IDX))["title"] == "Events"
