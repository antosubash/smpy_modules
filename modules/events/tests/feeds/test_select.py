"""The feed read: the public gate, the window, the caps, one query per kind of row."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.select import feed_events, single_event
from sm_events.models import Category, OccurrenceOverride
from sqlalchemy import event as sa_event

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event, seed_public_fixture, seed_series
from tests.support.public import add_german

NOW = datetime(2026, 4, 1, tzinfo=UTC)


def url_for(slug: str, locale: str) -> str:
    return f"https://x.example/{locale}/{slug}"


async def read(db, *, calendar_id=None, locale="en", now=NOW):
    return await feed_events(
        db, calendar_id=calendar_id, locale=locale, default_locale="en", now=now, url_for=url_for
    )


async def test_only_public_published(db):
    fx = await seed_public_fixture(db)
    got = await read(db)
    assert {i.event.uid for i in got.items} == {e.uid for e in fx.public_events}
    assert not got.truncated
    hidden = {e.uid for e in fx.hidden.values()}
    assert not hidden & {i.event.uid for i in got.items}


async def test_items_hold_texts_urls_categories_and_parents(db):
    fx = await seed_public_fixture(db)
    got = {i.event.id: i for i in (await read(db)).items}
    one_off = got[fx.one_off.id]
    assert one_off.text.locale == "en" and one_off.url == url_for(fx.slug(fx.one_off), "en")
    assert one_off.category == fx.public_cat.names["en"]
    assert got[fx.talk.id].parent_uid == fx.conf.uid
    assert got[fx.orphan.id].parent_uid is None  # its parent is a draft: never named
    assert got[fx.conf.id].parent_uid is None
    assert {o.kind for o in got[fx.series.id].overrides} == {"moved", "cancelled", "skipped"}
    assert got[fx.conf.id].overrides == ()


async def test_calendar_filter(db):
    fx = await seed_public_fixture(db)
    assert {i.event.id for i in (await read(db, calendar_id=fx.pub.id)).items} == {
        e.id for e in fx.public_events
    }
    for hidden in (fx.internal, fx.private, fx.gone):
        assert (await read(db, calendar_id=hidden.id)).items == []


async def test_window(db):
    cal = (await seed_calendars(db))["U"]
    kw = {"status": "published"}
    ended = await seed_event(
        db,
        cal,
        slug="ended",
        starts_at=NOW - timedelta(days=32),
        ends_at=NOW - timedelta(days=31),
        **kw,
    )
    far = await seed_event(db, cal, slug="far", starts_at=NOW + timedelta(days=367), **kw)
    inside = await seed_event(db, cal, slug="inside", starts_at=NOW + timedelta(days=364), **kw)
    straddles = await seed_event(
        db,
        cal,
        slug="straddles",
        starts_at=NOW - timedelta(days=40),
        ends_at=NOW - timedelta(days=29),
        **kw,
    )
    endless = await seed_series(
        db, cal, "FREQ=DAILY", "2024-01-01T10:00", "2024-01-01T11:00", slug="endless", **kw
    )
    over = await seed_series(
        db, cal, "FREQ=DAILY;COUNT=5", "2026-02-20T10:00", "2026-02-20T11:00", slug="over", **kw
    )
    got = {i.event.id for i in (await read(db)).items}
    assert {inside.id, straddles.id, endless.id} <= got
    assert not {ended.id, far.id, over.id} & got


async def test_caps(db, monkeypatch):
    cal = (await seed_calendars(db))["U"]
    for n in range(6):
        await seed_event(
            db, cal, slug=f"e{n}", status="published", starts_at=NOW + timedelta(days=n + 1)
        )
    monkeypatch.setattr(constants, "FEED_MAX_EVENTS", 5)
    got = await read(db)
    assert len(got.items) == 5 and got.truncated
    assert [i.text.slug for i in got.items] == [f"e{n}" for n in range(5)]  # by start


async def test_component_cap_drops_whole_series_and_everything_after(db, monkeypatch):
    cal = (await seed_calendars(db))["U"]
    kw = {"status": "published"}
    first = await seed_event(db, cal, slug="first", starts_at=NOW + timedelta(days=1), **kw)
    series = await seed_series(
        db, cal, "FREQ=DAILY;COUNT=20", "2026-04-05T10:00", "2026-04-05T11:00", slug="series", **kw
    )
    for day, kind in ((7, "cancelled"), (8, "cancelled"), (9, "skipped")):
        when = datetime(2026, 4, day, 8, tzinfo=UTC)
        db.add(OccurrenceOverride(event_id=series.id, original_start=when, kind=kind))
    last = await seed_event(db, cal, slug="last", starts_at=NOW + timedelta(days=30), **kw)
    await db.flush()
    # first = 1; the series = its master and all three overrides, the skip included = 4
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 6)
    got = await read(db)
    assert [i.event.id for i in got.items] == [first.id, series.id, last.id] and not got.truncated
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 5)
    got = await read(db)
    assert [i.event.id for i in got.items] == [first.id, series.id] and got.truncated
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 4)
    got = await read(db)
    assert [i.event.id for i in got.items] == [first.id] and got.truncated
    assert last.id not in {i.event.id for i in got.items}
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 100)
    assert not (await read(db)).truncated


async def _series_with(db, count: int, kind: str = "skipped", slug: str = "many"):
    cal = (await seed_calendars(db))["U"]
    series = await seed_series(
        db, cal, "FREQ=DAILY;COUNT=60", "2026-04-02T10:00", "2026-04-02T11:00",
        slug=slug, status="published",
    )  # fmt: skip
    for n in range(count):
        when = datetime(2026, 4, 2 + n, 8, tzinfo=UTC)
        db.add(OccurrenceOverride(event_id=series.id, original_start=when, kind=kind))
    await db.flush()
    return series


async def test_overrides_are_bounded_in_sql(db, db_state, monkeypatch):
    series = await _series_with(db, 12)
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 5)
    ran: list[str] = []
    sa_event.listen(
        db_state.engine.sync_engine,
        "before_cursor_execute",
        lambda c, cur, stmt, *a: ran.append(stmt),
    )
    got = await read(db)
    assert got.items == [] and got.truncated  # a cut series is never emitted without its EXDATEs
    assert series.id
    overrides = [stmt for stmt in ran if "events_occurrence_override" in stmt]
    assert len(overrides) == 1 and "LIMIT" in overrides[0].upper()


async def test_exactly_at_the_cap_and_one_past(db, monkeypatch):
    series = await _series_with(db, 4)  # master + 4 skips = 5 components
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 5)
    at = await read(db)
    assert [i.event.id for i in at.items] == [series.id] and not at.truncated
    assert len(at.items[0].overrides) == 4
    db.add(
        OccurrenceOverride(
            event_id=series.id, original_start=datetime(2026, 5, 20, 8, tzinfo=UTC), kind="skipped"
        )
    )
    await db.flush()
    past = await read(db)
    assert past.items == [] and past.truncated


async def test_skips_count_toward_the_cap(db, monkeypatch):
    await _series_with(db, 6, kind="skipped")
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 6)
    assert (await read(db)).truncated  # 1 + 6 skips = 7 > 6


async def test_the_single_event_file_is_capped_too(db, monkeypatch):
    series = await _series_with(db, 8)
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 5)
    got = await single_event(db, series, locale="en", default_locale="en", url_for=url_for)
    assert got.truncated and len(got.items) == 1 and len(got.items[0].overrides) == 5
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 8)
    exact = await single_event(db, series, locale="en", default_locale="en", url_for=url_for)
    assert not exact.truncated and len(exact.items[0].overrides) == 8


async def test_locale_fallback(db):
    fx = await seed_public_fixture(db)
    await add_german(db, fx)  # de on every public event
    english_only = await seed_event(db, fx.pub, slug="english-only", status="published")
    got = {i.event.id: i for i in (await read(db, locale="de")).items}
    assert got[fx.one_off.id].text.locale == "de"
    assert got[fx.one_off.id].url == url_for(fx.slug(fx.one_off, "de"), "de")
    assert got[english_only.id].text.locale == "en"
    assert got[english_only.id].url == url_for("english-only", "en")
    assert got[fx.one_off.id].category == fx.public_cat.names["en"]  # no de name: default


async def test_category_name_in_the_feed_language(db):
    fx = await seed_public_fixture(db)
    fx.public_cat.names = {"en": "Music", "de": "Musik"}
    await db.flush()
    en = {i.event.id: i for i in (await read(db)).items}
    de = {i.event.id: i for i in (await read(db, locale="de")).items}
    assert en[fx.one_off.id].category == "Music" and de[fx.one_off.id].category == "Musik"
    assert isinstance(fx.public_cat, Category)


async def test_single_event_has_no_window_and_all_overrides(db):
    cal = (await seed_calendars(db))["U"]
    old = await seed_series(
        db, cal, "FREQ=WEEKLY;COUNT=5", "2024-01-01T10:00", "2024-01-01T11:00",
        slug="old", status="published",
    )  # fmt: skip
    for day in (8, 15):
        when = datetime(2024, 1, day, 9, tzinfo=UTC)
        db.add(OccurrenceOverride(event_id=old.id, original_start=when, kind="skipped"))
    await db.flush()
    assert old.id not in {i.event.id for i in (await read(db)).items}  # outside the window
    got = await single_event(db, old, locale="en", default_locale="en", url_for=url_for)
    (item,) = got.items
    assert item.event.id == old.id and len(item.overrides) == 2 and not got.truncated


async def test_query_count(db, db_state):
    cal = (await seed_calendars(db))["U"]
    cat = Category(slug="c-x", names={"en": "X"})
    db.add(cat)
    await db.flush()
    parent = await seed_event(db, cal, slug="parent", status="published")
    for n in range(50):
        await seed_event(
            db,
            cal,
            slug=f"e{n}",
            status="published",
            starts_at=NOW + timedelta(days=n + 1),
            category_id=cat.id,
            parent_id=parent.id if n % 2 else None,
        )
    ran: list[str] = []
    sa_event.listen(
        db_state.engine.sync_engine,
        "before_cursor_execute",
        lambda c, cur, stmt, *a: ran.append(stmt),
    )
    got = await read(db)
    assert len(got.items) == 51
    assert len(ran) <= 5, ran


@pytest.mark.unbound_tenant
async def test_other_tenant(db):
    with tenant_scope("b"):
        other = await seed_public_fixture(db, tag="-b")
    with tenant_scope("a"):
        mine = await seed_public_fixture(db, tag="-a")
        got = await read(db)
        uids = {i.event.uid for i in got.items}
        assert uids == {e.uid for e in mine.public_events}
        assert not uids & {e.uid for e in other.public_events}
        assert (await read(db, calendar_id=other.pub.id)).items == []


async def test_a_single_file_cut_by_the_override_cap_ends_its_rule_there(db, monkeypatch):
    """A skip after the cut would come back as a confirmed occurrence in a client that expands
    the full rule, so the file's rule stops just before the first override it does not carry."""
    from dateutil import rrule as du
    from sm_events.feeds.ics_event import components

    series = await _series_with(db, 8)  # skipped on Apr 2..9, at 08:00 UTC (10:00 Vienna)
    monkeypatch.setattr(constants, "FEED_MAX_COMPONENTS", 5)
    got = await single_event(db, series, locale="en", default_locale="en", url_for=url_for)
    assert got.truncated
    master = components(got.items[0])[0]
    rule = master["RRULE"]
    assert "COUNT" not in rule and "UNTIL" in rule
    start = master.decoded("DTSTART")
    until = rule["UNTIL"][0]
    expanded = du.rrulestr(
        f"FREQ=DAILY;UNTIL={until:%Y%m%dT%H%M%SZ}", dtstart=start.astimezone(UTC)
    )
    skipped = {d.dt.astimezone(UTC) for d in master["EXDATE"].dts}
    confirmed = [i for i in expanded if i not in skipped]
    # The five carried skips (Apr 2-6) stay skipped, and nothing after them is generated, so the
    # uncarried skips (Apr 7-9) cannot come back as confirmed occurrences.
    assert confirmed == [] and max(expanded).date() == date(2026, 4, 6)
