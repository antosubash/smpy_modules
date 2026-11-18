"""One event's page: occurrences, sub-events, languages, redirects and what it never names."""

from __future__ import annotations

import json

import pytest
from sm_events.content.texts import apply_texts
from sm_events.models import Event, EventText
from sm_events.web.schemas.texts import TextIn
from sqlalchemy import select

from tests.support.public import INERTIA, seed_public

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


async def test_one_off_page(public_locales_client, fx):
    slug = fx.slug(fx.one_off)
    got = await get(public_locales_client, f"/events/{slug}")
    p = props(got)
    assert p["title"] == slug.title() and p["locale"] == "en" and p["timezone"] == "UTC"
    assert p["when"]["start_local"] == "2026-07-01T10:00" and p["when"]["status"] == "scheduled"
    assert p["series"] is None and p["cancelled"] is False and p["parent"] is None
    assert p["ics_url"] == f"/events/{slug}.ics"
    assert p["canonical_url"] == f"http://test/events/{slug}"
    assert p["calendar"] == {
        "slug": fx.pub.slug,
        "name": fx.pub.name,
        "color": fx.pub.color,
        "url": f"/events/c/{fx.pub.slug}",
    }
    assert p["category"]["slug"] == fx.public_cat.slug and p["index_in_search"] is True
    assert got.headers["content-language"] == "en" and got.headers["etag"].startswith('W/"')
    again = await get(
        public_locales_client, f"/events/{slug}", **{"If-None-Match": got.headers["etag"]}
    )
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == got.headers["etag"]
    for key in (
        "when",
        "series",
        "description_tree",
        "sub_events",
        "alternates",
        "json_ld",
        "place",
    ):
        assert key in p


@pytest.mark.parametrize(
    ("date", "outcome"),
    [
        ("2026-03-16", "scheduled"),
        ("2026-03-30", "rescheduled"),
        ("2026-04-06", "cancelled"),
        ("2026-04-20", "scheduled"),
        ("2026-04-13", 404),  # skipped
        ("2026-04-14", 404),  # a Tuesday
        ("2026-13-40", 404),
        ("2026-4-6", 404),
        ("20260406", 404),
        ("", 404),
        ("abc", 404),
        ("0001-01-01", 404),
        ("9999-12-31", 404),
        ("2026-04-06T10:00", 404),
    ],
)
async def test_date_param_matrix(public_locales_client, fx, date, outcome):
    got = await get(public_locales_client, f"/events/{fx.slug(fx.series)}?date={date}")
    if outcome == 404:
        assert got.status_code == 404 and got.json()["component"] == "Events/PublicNotFound"
        return
    p = props(got)
    assert p["when"]["status"] == outcome and p["when"]["date_param"] == date
    assert p["canonical_url"] == f"http://test/events/{fx.slug(fx.series)}?date={date}"
    assert isinstance(p["json_ld"], dict)
    if outcome == "rescheduled":
        assert p["when"]["start_local"] == "2026-03-30T11:00"
        assert p["when"]["previous_start_local"] == "2026-03-30T10:00"
        assert p["json_ld"]["eventStatus"].endswith("EventRescheduled")
    if outcome == "cancelled":
        assert p["cancelled"] is True and p["json_ld"]["eventStatus"].endswith("EventCancelled")
        assert p["registration_url"] is None


async def test_date_param_on_a_one_off_and_a_hidden_event(public_locales_client, fx):
    missing = await get(public_locales_client, "/events/no-such?date=2026-04-06")
    for slug in (fx.slug(fx.one_off), fx.slug(fx.draft), fx.slug(fx.internal_event)):
        got = await get(public_locales_client, f"/events/{slug}?date=2026-07-01")
        assert got.status_code == 404 and got.json()["props"] == missing.json()["props"], slug


async def test_bare_series_page(public_locales_client, fx):
    p = props(await get(public_locales_client, f"/events/{fx.slug(fx.series)}"))
    assert p["when"] is None and p["series"]["rule"].startswith("FREQ=WEEKLY")
    assert p["series"]["start_local"] == "2026-03-16T10:00"
    nxt = p["series"]["next"]
    assert [n["date_param"] for n in nxt] == [
        "2026-04-06",
        "2026-04-20",
        "2026-04-27",
        "2026-05-04",
    ]
    assert nxt[0]["status"] == "cancelled" and nxt[1]["status"] == "scheduled"
    assert nxt[1]["url"] == f"/events/{fx.slug(fx.series)}?date=2026-04-20"
    assert "2026-04-13" not in json.dumps(nxt)  # the skipped week
    assert isinstance(p["json_ld"], list) and len(p["json_ld"]) == 4
    assert p["canonical_url"] == f"http://test/events/{fx.slug(fx.series)}"


async def test_alternates_only_public_texts(public_locales_client, fx_partial):
    fx = fx_partial
    p = props(await get(public_locales_client, f"/events/{fx.slug(fx.one_off)}"))
    assert p["alternates"] == [
        {"locale": "en", "url": f"http://test/events/{fx.slug(fx.one_off)}"},
        {"locale": "de", "url": f"http://test/de/events/{fx.slug(fx.one_off, 'de')}"},
        {"locale": "x-default", "url": f"http://test/events/{fx.slug(fx.one_off)}"},
    ]
    only_en = props(await get(public_locales_client, f"/events/{fx.slug(fx.conf)}"))
    assert only_en["alternates"] == []
    de = props(await get(public_locales_client, f"/de/events/{fx.slug(fx.one_off, 'de')}"))
    assert de["locale"] == "de" and de["canonical_url"].endswith(
        f"/de/events/{fx.slug(fx.one_off, 'de')}"
    )
    assert [a["locale"] for a in de["alternates"]] == ["en", "de", "x-default"]


async def test_hidden_german_texts_are_never_named(public_locales_client, fx):
    text = (await public_locales_client.get(f"/events/{fx.slug(fx.one_off)}")).text
    for event in fx.hidden.values():
        for locale in ("en", "de"):
            assert (
                fx.slug(event, locale) not in text if f"{event.id}:{locale}" in fx.slugs else True
            )


async def test_locale_only_where_text(public_locales_client, fx_partial):
    fx = fx_partial
    assert (await get(public_locales_client, f"/de/events/{fx.slug(fx.conf)}")).status_code == 404
    assert (
        await get(public_locales_client, f"/events/{fx.slug(fx.one_off, 'de')}")
    ).status_code == 404


async def test_slug_redirect(public_locales_client, fx):
    old = fx.slug(fx.series, "de")

    async def rename(db):
        event = await db.get(Event, fx.series.id)
        await apply_texts(
            db,
            event,
            {"de": TextIn(title="Neu", slug="neuer-slug")},
            locales=("en", "de"),
            creating=False,
        )

    await mutate(public_locales_client, rename)
    got = await public_locales_client.get(f"/de/events/{old}")
    assert got.status_code == 301 and got.headers["location"] == "/de/events/neuer-slug"
    keep = await public_locales_client.get(f"/de/events/{old}?date=2026-04-20")
    assert keep.headers["location"] == "/de/events/neuer-slug?date=2026-04-20"
    assert props(await get(public_locales_client, keep.headers["location"]))["title"] == "Neu"
    wrong_language = await get(public_locales_client, f"/events/{old}")
    assert wrong_language.status_code == 404  # the redirect is the German one only


async def test_sub_events(public_locales_client, fx):
    conf = props(await get(public_locales_client, f"/events/{fx.slug(fx.conf)}"))
    assert [i["title"] for i in conf["sub_events"]] == [fx.slug(fx.talk).title()]
    assert conf["sub_events"][0]["url"] == f"/events/{fx.slug(fx.talk)}"
    assert fx.slug(fx.secret_talk) not in json.dumps(conf).lower()
    talk = props(await get(public_locales_client, f"/events/{fx.slug(fx.talk)}"))
    assert talk["parent"] == {
        "title": fx.slug(fx.conf).title(),
        "url": f"/events/{fx.slug(fx.conf)}",
    }


async def test_child_of_hidden_parent_names_no_parent(public_locales_client, fx):
    got = await public_locales_client.get(f"/events/{fx.slug(fx.orphan)}")
    assert (
        got.status_code == 200
        and props(await get(public_locales_client, f"/events/{fx.slug(fx.orphan)}"))["parent"]
        is None
    )
    html = got.text
    parent = fx.slug(fx.draft_parent)
    assert parent not in html and parent.title() not in html


async def test_a_sub_event_on_another_public_calendar_shows_its_own(public_locales_client, fx):
    """The page lists a child with its own calendar's name and colour, and compares its zone with
    that calendar's default, not the parent's."""
    from sm_events.core.tenancy import tenant_scope
    from sm_events.models import Calendar, Visibility

    from tests.support.calendars import seed_event

    with tenant_scope("default"):
        async with public_locales_client.db_state.session_factory() as s:
            other = Calendar(
                slug="other-cal", name="Other Cal", owner_id="o", visibility=Visibility.PUBLIC,
                color="#ff0000", default_timezone="America/New_York",
            )  # fmt: skip
            s.add(other)
            await s.flush()
            conf = (await s.execute(select(Event).where(Event.id == fx.conf.id))).scalar_one()
            await seed_event(
                s, other, title="Side", slug="side-session", status="published",
                parent_id=conf.id, timezone="America/New_York",
            )  # fmt: skip
            await s.commit()
    got = props(await get(public_locales_client, f"/events/{fx.slug(fx.conf)}"))
    side = next(i for i in got["sub_events"] if i["url"] == "/events/side-session")
    assert side["calendar"]["slug"] == "other-cal" and side["calendar"]["color"] == "#ff0000"
    assert side["show_timezone"] is False  # New York on a New York calendar
    talk = next(i for i in got["sub_events"] if i["url"] == f"/events/{fx.slug(fx.talk)}")
    assert talk["calendar"]["slug"] == fx.pub.slug
