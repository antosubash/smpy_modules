"""The upcoming list (``/``) and one calendar's page (``/c/{calendar}``), server side."""

from __future__ import annotations

import math
from datetime import timedelta

import pytest
from sm_events.calendar import calendars
from sm_events.models import Calendar
from sm_events.web.endpoints.public import _urls
from sm_events.web.schemas.calendars import CalendarPatch

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


async def test_index_props(public_locales_client, fx):
    p = props(await get(public_locales_client, IDX))
    items = flat(p)
    titles = [i["title"] for i in items]
    assert fx.slug(fx.one_off).title() in titles and fx.slug(fx.conf).title() in titles
    for event in fx.hidden.values():
        assert fx.slug(event).title() not in titles
    # by local month, in order, and the items agree with their group
    months = [g["month"] for g in p["groups"]]
    assert months == sorted(set(months)) == ["2026-04", "2026-05", "2026-07"]
    for group in p["groups"]:
        assert all(i["start_local"][:7] == group["month"] for i in group["items"])
    starts = [i["start_local"] for i in items]
    assert starts == sorted(starts)
    assert p["page"] == 1 and p["page_count"] == 1
    assert [c["id"] for c in p["calendars"]] == [str(fx.pub.id)]
    assert p["calendars"][0]["slug"] == fx.pub.slug
    assert [(c["slug"]) for c in p["categories"]] == [fx.public_cat.slug]
    assert p["category"] is None and p["calendar"] is None and p["view"] == "list"
    assert p["feed_url"] == "/events/calendar.ics" and p["api_url"] == "/events/api/occurrences"
    assert p["locale"] == "en"


async def test_item_shape(public_locales_client, fx):
    items = {i["key"]: i for i in flat(props(await get(public_locales_client, IDX)))}
    one = next(i for i in items.values() if i["title"] == fx.slug(fx.one_off).title())
    assert set(one) == {
        "key", "url", "title", "lang", "all_day", "start_local", "end_local", "start_date",
        "end_date", "timezone", "show_timezone", "status", "rescheduled", "calendar", "category",
        "venue_name", "attendance_mode", "summary", "image",
    }  # fmt: skip
    assert one["url"] == f"/events/{fx.slug(fx.one_off)}" and one["timezone"] == "UTC"
    assert one["calendar"] == {"slug": fx.pub.slug, "name": fx.pub.name, "color": fx.pub.color}
    assert one["category"]["slug"] == fx.public_cat.slug
    assert one["status"] == "confirmed" and one["rescheduled"] is False
    cancelled = [i for i in items.values() if i["status"] == "cancelled"]
    assert len(cancelled) == 1 and cancelled[0]["url"].endswith("?date=2026-04-06")
    # the series is in Europe/Vienna while its calendar is UTC: the zone is named
    assert any(i["show_timezone"] for i in items.values() if i["timezone"] == "Europe/Vienna")


async def test_paging(public_locales_client, fx):
    async def add(db):
        cal = await db.get(Calendar, fx.pub.id)
        for n in range(45):
            await seed_event(
                db, cal, slug=f"more-{n:02d}", title=f"More {n:02d}", status="published",
                starts_at=NOW + timedelta(days=10 + n),
                ends_at=NOW + timedelta(days=10 + n, hours=1),
            )  # fmt: skip

    async with public_locales_client.db_state.session_factory() as db:
        await add(db)
        await db.commit()
    first = props(await get(public_locales_client, IDX))
    assert first["page_count"] == math.ceil((8 + 45) / 20) == 3
    assert len(flat(first)) == 20
    third = props(await get(public_locales_client, f"{IDX}?page=3"))
    assert third["page"] == 3 and len(flat(third)) == 13
    seen = [
        i["key"]
        for p in (1, 2, 3)
        for i in flat(props(await get(public_locales_client, f"{IDX}?page={p}")))
    ]
    assert len(seen) == len(set(seen)) == 53  # no overlap, nothing lost, stable order
    for lenient in ("0", "abc", "-4", "", "1.5"):
        assert props(await get(public_locales_client, f"{IDX}?page={lenient}"))["page"] == 1, (
            lenient
        )
    assert props(await get(public_locales_client, f"{IDX}?page=0000000000002"))["page"] == 2
    for beyond in ("4", "99999999", "99999999999999999999", "9" * 5000, "1" + "0" * 4400):
        got = await get(public_locales_client, f"{IDX}?page={beyond}")
        assert got.status_code == 404 and got.json()["component"] == "Events/PublicNotFound", beyond


async def test_category_filter(public_locales_client, fx):
    p = props(await get(public_locales_client, f"{IDX}?category={fx.public_cat.slug}"))
    assert [i["title"] for i in flat(p)] == [fx.slug(fx.one_off).title()] and p[
        "category"
    ] == fx.public_cat.slug
    missing = await get(public_locales_client, f"{IDX}?category=nope")
    hidden = await get(public_locales_client, f"{IDX}?category={fx.draft_cat.slug}")
    for got in (missing, hidden):
        assert got.status_code == 404
    assert hidden.json()["props"] == missing.json()["props"]
    assert (await get(public_locales_client, f"{IDX}?category=%00")).status_code == 404
    assert props(await get(public_locales_client, f"{IDX}?category="))["category"] is None


async def test_view_param(public_locales_client, fx):
    assert props(await get(public_locales_client, f"{IDX}?view=calendar"))["view"] == "calendar"
    for other in ("list", "grid", "<script>", ""):
        assert props(await get(public_locales_client, f"{IDX}?view={other}"))["view"] == "list"


async def test_calendar_page(public_locales_client, fx):
    p = props(await get(public_locales_client, f"/events/c/{fx.pub.slug}"))
    assert (
        p["calendar"]["slug"] == fx.pub.slug and p["calendar"]["url"] == f"/events/c/{fx.pub.slug}"
    )
    assert p["calendar"]["feed_url"] == f"/events/c/{fx.pub.slug}.ics"
    assert len(flat(p)) == 8
    assert p["calendar"]["color"] == fx.pub.color and p["calendar"]["default_timezone"] == "UTC"
    narrowed = props(
        await get(public_locales_client, f"/events/c/{fx.pub.slug}?category={fx.public_cat.slug}")
    )
    assert len(flat(narrowed)) == 1


async def test_calendar_rename_redirects(public_locales_client, fx):
    async with public_locales_client.db_state.session_factory() as db:
        cal = await db.get(Calendar, fx.pub.id)
        await calendars.update_calendar(db, cal, CalendarPatch(slug="renamed"))
        await db.commit()
    old = await public_locales_client.get(f"/events/c/{fx.pub.slug}?page=2&category=x")
    assert old.status_code == 301
    assert old.headers["location"] == "/events/c/renamed?page=2&category=x"
    assert (
        props(await get(public_locales_client, "/events/c/renamed"))["calendar"]["slug"]
        == "renamed"
    )


async def test_hidden_calendars_are_the_404(public_locales_client, fx):
    missing = await get(public_locales_client, "/events/c/never-existed")
    for hidden in (fx.internal, fx.private, fx.gone):
        got = await get(public_locales_client, f"/events/c/{hidden.slug}")
        assert got.status_code == 404 and got.json()["props"] == missing.json()["props"]


async def test_head_injected(public_locales_client, fx):
    got = await public_locales_client.get("/de/events/")
    html = got.text
    assert got.status_code == 200 and '<html lang="de"' in html
    assert "<title>Events</title>" in html
    assert '<link rel="canonical" data-inertia="canonical" href="http://test/de/events/">' in html
    for locale, url in (
        ("en", "http://test/events/"),
        ("de", "http://test/de/events/"),
        ("x-default", "http://test/events/"),
    ):
        assert (
            f'<link rel="alternate" data-inertia="hreflang-{locale}" '
            f'hreflang="{locale}" href="{url}">'
        ) in html
    assert 'type="text/calendar"' in html and 'href="http://test/de/events/calendar.ics"' in html
    assert got.headers["content-language"] == "de"


async def test_head_of_a_calendar_page(public_locales_client, fx):
    html = (await public_locales_client.get(f"/events/c/{fx.pub.slug}")).text
    assert f"<title>{fx.pub.name}</title>" in html
    assert f'href="http://test/events/c/{fx.pub.slug}.ics"' in html


async def test_canonical_ignores_the_view_and_keeps_filters(public_locales_client, fx):
    html = (
        await public_locales_client.get(f"{IDX}?view=calendar&category={fx.public_cat.slug}")
    ).text
    assert (
        'rel="canonical" data-inertia="canonical" '
        f'href="http://test/events/?category={fx.public_cat.slug}"'
    ) in html


async def test_a_configured_origin_beats_a_spoofed_host(public_locales_client, fx):
    public_locales_client.app.state.sm.settings.public_base_url = "https://site.example/"
    got = await public_locales_client.get(
        IDX, headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example"}
    )
    assert 'href="https://site.example/events/"' in got.text and "evil.example" not in got.text
    assert "Host" not in got.headers.get("vary", "")


async def test_fallback_marked(public_locales_client, fx_partial):
    fx = fx_partial
    items = {i["key"]: i for i in flat(props(await get(public_locales_client, "/de/events/")))}
    conf = next(i for i in items.values() if i["title"] == fx.slug(fx.conf).title())
    assert conf["lang"] == "en" and conf["url"] == f"/events/{fx.slug(fx.conf)}"
    one = next(i for i in items.values() if i["title"] == fx.slug(fx.one_off, "de").title())
    assert one["lang"] == "de" and one["url"] == f"/de/events/{fx.slug(fx.one_off, 'de')}"


async def test_not_found_suggestions(public_locales_client, fx):
    first = flat(props(await get(public_locales_client, IDX)))[:3]
    draft = await get(public_locales_client, _urls.event_path(fx.slug(fx.draft), "en"))
    missing = await get(public_locales_client, "/events/no-such-event")
    assert draft.status_code == missing.status_code == 404
    suggestions = missing.json()["props"]["suggestions"]
    assert [s["key"] for s in suggestions] == [i["key"] for i in first] and len(suggestions) == 3
    assert draft.json()["props"] == missing.json()["props"]


async def test_signed_in_manager_sees_public_only(public_locales_client, fx):
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    for path in (IDX, f"/events/c/{fx.pub.slug}"):
        anon = props(await get(public_locales_client, path))
        signed = props(await get(public_locales_client, path, **manager))
        assert signed["groups"] == anon["groups"] and signed["calendars"] == anon["calendars"]
        assert signed["categories"] == anon["categories"]


async def test_no_admin_links_in_the_props(public_locales_client, fx):
    assert "/admin/" not in (await get(public_locales_client, IDX)).text


@pytest.mark.unbound_tenant
async def test_other_tenant_and_no_tenant(public_multi_client):
    mine = await seed_public(public_multi_client, tag="-a", tenant="a")
    theirs = await seed_public(public_multi_client, tag="-b", tenant="b")
    got = await get(public_multi_client, IDX, **{"X-Test-Tenant": "a"})
    text = got.text
    assert theirs.slug(theirs.one_off) not in text and mine.slug(mine.one_off) in text
    assert got.headers["cache-control"].startswith("private")
    assert (await get(public_multi_client, IDX)).status_code == 404
    cross = await get(public_multi_client, f"/events/c/{theirs.pub.slug}", **{"X-Test-Tenant": "a"})
    assert cross.status_code == 404
