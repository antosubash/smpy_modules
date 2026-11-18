"""``/calendar.ics``, ``/c/{calendar}.ics`` and ``/{slug}.ics`` over HTTP."""

from __future__ import annotations

from datetime import UTC, datetime

import icalendar
import pytest
from sm_events.core import constants
from sm_events.models import Calendar, Event, OccurrenceOverride
from sm_events.web.endpoints.public import _feeds, _urls

from tests.support.app import as_user
from tests.support.calendars import seed_event
from tests.support.public import seed_public

NOW = datetime(2026, 4, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(_feeds, "utcnow", lambda: NOW)


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client)


def events_of(response) -> list[icalendar.Event]:
    return list(icalendar.Calendar.from_ical(response.content).walk("VEVENT"))


def uids(response) -> set[str]:
    return {str(e["UID"]) for e in events_of(response)}


async def mutate(client, fn):
    async with client.db_state.session_factory() as session:
        out = await fn(session)
        await session.commit()
        return out


async def test_content_type_and_disposition(public_locales_client, fx):
    feed = await public_locales_client.get(_urls.calendar_ics_path(None, "en"))
    assert feed.status_code == 200
    assert feed.headers["content-type"] == "text/calendar; charset=utf-8"
    assert "content-disposition" not in feed.headers
    one = await public_locales_client.get(_urls.event_ics_path(fx.slug(fx.one_off), "en"))
    assert one.headers["content-type"] == "text/calendar; charset=utf-8"
    assert one.headers["content-disposition"] == f'attachment; filename="{fx.slug(fx.one_off)}.ics"'
    assert one.content.startswith(b"BEGIN:VCALENDAR\r\n")


async def test_calendar_feed_body(public_locales_client, fx):
    got = await public_locales_client.get(_urls.calendar_ics_path(None, "en"))
    assert uids(got) == {e.uid for e in fx.public_events}
    series = [e for e in events_of(got) if str(e["UID"]) == fx.series.uid]
    assert len(series) == 3  # master, moved, cancelled
    master = next(e for e in series if "RRULE" not in e or "RECURRENCE-ID" not in e)
    assert "RRULE" in master and "EXDATE" in master
    assert sum("RECURRENCE-ID" in e for e in series) == 2
    assert str(icalendar.Calendar.from_ical(got.content)["X-WR-CALNAME"]) == constants.MODULE_NAME


async def test_one_calendar_feed(public_locales_client, fx):
    got = await public_locales_client.get(_urls.calendar_ics_path(fx.pub.slug, "en"))
    assert uids(got) == {e.uid for e in fx.public_events}
    cal = icalendar.Calendar.from_ical(got.content)
    assert str(cal["X-WR-CALNAME"]) == fx.pub.name


async def test_hidden_rows_are_not_in_any_feed(public_locales_client, fx):
    hidden = {e.uid for e in fx.hidden.values()}
    for path in (_urls.calendar_ics_path(None, "en"), _urls.calendar_ics_path(fx.pub.slug, "en")):
        assert not hidden & uids(await public_locales_client.get(path))


async def test_single_series_has_all_overrides(public_locales_client, fx):
    async def add(db):
        when = datetime(2025, 2, 3, 9, tzinfo=UTC)  # 400+ days before the window
        db.add(OccurrenceOverride(event_id=fx.series.id, original_start=when, kind="skipped"))

    await mutate(public_locales_client, add)
    feed = await public_locales_client.get(_urls.calendar_ics_path(None, "en"))
    one = await public_locales_client.get(_urls.event_ics_path(fx.slug(fx.series), "en"))
    n_feed = len(next(e for e in events_of(feed) if "RRULE" in e)["EXDATE"].dts)
    n_one = len(next(e for e in events_of(one) if "RRULE" in e)["EXDATE"].dts)
    assert n_one == 2 and n_feed == 2  # both carry every skip, in or out of the window
    assert len(events_of(one)) == 3


async def test_single_event_is_not_windowed(public_locales_client, fx):
    async def old(db):
        row = await db.get(Event, fx.one_off.id)
        row.starts_at = datetime(2020, 1, 1, 8, tzinfo=UTC)
        row.ends_at = datetime(2020, 1, 1, 9, tzinfo=UTC)

    await mutate(public_locales_client, old)
    assert fx.one_off.uid not in uids(
        await public_locales_client.get(_urls.calendar_ics_path(None, "en"))
    )
    one = await public_locales_client.get(_urls.event_ics_path(fx.slug(fx.one_off), "en"))
    assert uids(one) == {fx.one_off.uid}


async def test_etag_and_304(public_locales_client, fx):
    path = _urls.calendar_ics_path(None, "en")
    first = await public_locales_client.get(path)
    tag = first.headers["etag"]
    assert tag.startswith('W/"')
    again = await public_locales_client.get(path, headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == tag
    assert again.headers["cache-control"] == first.headers["cache-control"]
    assert again.headers["vary"] == first.headers["vary"]
    assert "content-security-policy" not in again.headers

    async def bump(db):
        row = await db.get(Event, fx.series.id)
        row.revision += 1
        db.add(
            OccurrenceOverride(
                event_id=fx.series.id,
                original_start=datetime(2026, 5, 4, 8, tzinfo=UTC),
                kind="cancelled",
            )
        )

    await mutate(public_locales_client, bump)
    after = await public_locales_client.get(path, headers={"If-None-Match": tag})
    assert after.status_code == 200 and after.headers["etag"] != tag


async def test_single_event_etag_changes_with_its_revision(public_locales_client, fx):
    path = _urls.event_ics_path(fx.slug(fx.one_off), "en")
    tag = (await public_locales_client.get(path)).headers["etag"]
    assert (
        await public_locales_client.get(path, headers={"If-None-Match": tag})
    ).status_code == 304

    async def bump(db):
        (await db.get(Event, fx.one_off.id)).revision += 1

    await mutate(public_locales_client, bump)
    assert (
        await public_locales_client.get(path, headers={"If-None-Match": tag})
    ).status_code == 200


@pytest.mark.unbound_tenant  # a tenant bound around the app would itself be "request-specific"
async def test_cache_kind_feed(public_locales_client, fx):
    got = await public_locales_client.get(_urls.calendar_ics_path(None, "en"))
    assert got.headers["cache-control"] == "public, max-age=300"
    assert "Host" in got.headers["vary"]  # the harness host has no public_base_url


async def test_no_store_when_the_setting_is_zero(public_locales_client, fx):
    public_locales_client.app.state.sm_events.settings.public_cache_seconds = 0
    got = await public_locales_client.get(_urls.calendar_ics_path(None, "en"))
    assert got.headers["cache-control"] == "no-store" and "etag" not in got.headers


async def test_head_has_the_headers_and_no_body(public_locales_client, fx):
    path = _urls.calendar_ics_path(None, "en")
    get, head = await public_locales_client.get(path), await public_locales_client.head(path)
    assert head.status_code == 200 and head.content == b""
    assert head.headers["etag"] == get.headers["etag"]
    assert head.headers["content-length"] == str(len(get.content))
    assert head.headers["content-type"] == get.headers["content-type"]


async def test_truncated_header(public_locales_client, fx, monkeypatch):
    path = _urls.calendar_ics_path(None, "en")
    assert "x-events-truncated" not in (await public_locales_client.get(path)).headers
    monkeypatch.setattr(constants, "FEED_MAX_EVENTS", 1)
    got = await public_locales_client.get(path)
    assert got.headers["x-events-truncated"] == "1" and len(uids(got)) == 1


async def test_german_feed(public_locales_client, fx):
    async def add(db):
        return (
            await seed_event(
                db, await db.get(Calendar, fx.pub.id), slug="english-only", status="published"
            )
        ).uid

    only_en = await mutate(public_locales_client, add)
    got = await public_locales_client.get(_urls.calendar_ics_path(None, "de"))
    by_uid = {str(e["UID"]): e for e in events_of(got) if "RECURRENCE-ID" not in e}
    assert str(by_uid[fx.one_off.uid]["SUMMARY"]) == fx.slug(fx.one_off, "de").title()
    assert str(by_uid[only_en]["SUMMARY"]) == "Event"  # no German text: the English one
    assert str(by_uid[fx.one_off.uid]["URL"]).endswith(f"/de/events/{fx.slug(fx.one_off, 'de')}")


async def test_single_event_needs_a_text_in_the_language(public_locales_client, fx):
    ok = await public_locales_client.get(_urls.event_ics_path(fx.slug(fx.one_off, "de"), "de"))
    assert ok.status_code == 200
    assert (
        await public_locales_client.get(_urls.event_ics_path(fx.slug(fx.conf), "de"))
    ).status_code == 404


async def test_not_found_is_the_json_envelope_with_no_store(public_locales_client, fx):
    for path in ("/events/nope.ics", "/events/c/nope.ics"):
        got = await public_locales_client.get(path)
        assert got.status_code == 404 and got.json()["code"] == "not_found"
        assert got.headers["cache-control"] == "no-store" and "etag" not in got.headers


async def test_a_signed_in_manager_gets_the_same_bytes(public_locales_client, fx):
    path = _urls.calendar_ics_path(None, "en")
    anon = await public_locales_client.get(path)
    manager = as_user("m", "events.view", "events.manage", "events.publish")
    signed = await public_locales_client.get(path, headers=manager)
    assert signed.content == anon.content


async def test_the_filename_is_ascii_safe(public_locales_client, fx):
    assert _feeds.safe_filename('a"b\r\nc/ü') == "a-b--c--"
    assert _feeds.safe_filename("") == constants.EVENT_SLUG_FALLBACK
