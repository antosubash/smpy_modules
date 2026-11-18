"""``sm_events.contracts.cards``: what a newsletter or a block may learn of an event."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from simple_module_db import like_contains_pattern
from sm_events import contracts
from sm_events.contracts import cards as contract
from sm_events.core import locales
from sm_events.models import EventText
from sm_events.web.endpoints.public import _clock

from tests.support.access import seed_calendars
from tests.support.calendars import seed_event, seed_public_fixture, seed_series
from tests.support.public import add_german
from tests.web.public.leaks import HIDDEN, LOCALES

NOW = datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
ANY = like_contains_pattern("")  # every title


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(_clock, "now", lambda: NOW)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def _search(db, pattern=ANY, **kw):
    return await contract.search_events(db, tenant_id="default", pattern=pattern, **kw)


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("hidden", HIDDEN)
async def test_hidden_events_never_carded(db, hidden, locale):
    locales.use("en", "de")
    fx = await seed_public_fixture(db)
    await add_german(db, fx)
    event = fx.hidden[hidden]
    title = await _title(db, event.id, locale)
    twin = await seed_event(
        db,
        fx.pub,
        title=title,
        slug=f"twin-{hidden}-{locale}",
        status="published",
        starts_at=utc(2026, 7, 10, 9),
    )
    db.add(EventText(event_id=twin.id, locale="de", slug=f"zwilling-{hidden}", title=title))
    await db.flush()
    assert (
        await contract.get_event_card(db, tenant_id="default", event_id=event.id, locale=locale)
        is None
    )
    found = await _search(db, like_contains_pattern(title), locale=locale)
    assert [c.id for c in found] == [twin.id]  # the public twin with the same title is found
    everything = await _search(db, locale=locale, limit=50, upcoming_only=False)
    assert event.id not in {c.id for c in everything}
    assert {e.id for e in fx.hidden.values()}.isdisjoint({c.id for c in everything})


async def _title(db, event_id, locale):
    from sqlmodel import col, select

    stmt = select(EventText.title).where(
        col(EventText.event_id) == event_id, col(EventText.locale) == locale
    )
    return (await db.execute(stmt)).scalar_one()


async def test_the_public_cast_is_found(db, monkeypatch):
    monkeypatch.setattr(_clock, "now", lambda: utc(2026, 4, 1))  # the fixture's series runs
    fx = await seed_public_fixture(db)
    got = await _search(db, upcoming_only=False, limit=50)
    assert {c.id for c in got} <= {e.id for e in fx.public_events}
    assert fx.one_off.id in {c.id for c in got}
    for event in fx.public_events:
        card = await contract.get_event_card(db, tenant_id="default", event_id=event.id)
        assert card is not None and card.id == event.id


async def test_search_matches_any_locale_title_and_escapes(db):
    locales.use("en", "de")
    cal = (await seed_calendars(db))["U"]
    both = await seed_event(db, cal, title="Sale", slug="sale", status="published")
    db.add(EventText(event_id=both.id, locale="de", slug="verkauf", title="Ausverkauf"))
    await seed_event(db, cal, title="50% off", slug="half", status="published")
    await seed_event(db, cal, title="500 off", slug="five", status="published")
    await db.flush()
    found = await _search(db, like_contains_pattern("verkauf"))
    assert [c.id for c in found] == [both.id]
    assert found[0].locale == "en"  # no locale asked: the default language's text
    in_german = await _search(db, like_contains_pattern("verkauf"), locale="de")
    assert [(c.title, c.locale) for c in in_german] == [("Ausverkauf", "de")]
    percent = await _search(db, like_contains_pattern("50%"))
    assert [c.title for c in percent] == ["50% off"]


async def test_upcoming_only(db):
    cal = (await seed_calendars(db))["U"]
    past = await seed_event(db, cal, title="past", status="published", starts_at=utc(2026, 6, 1))
    older = await seed_event(db, cal, title="older", status="published", starts_at=utc(2026, 5, 1))
    ahead = await seed_event(db, cal, title="ahead", status="published", starts_at=utc(2026, 8, 1))
    assert [c.id for c in await _search(db)] == [ahead.id]
    both = await _search(db, upcoming_only=False)
    assert [c.id for c in both] == [ahead.id, past.id, older.id]  # past ones: newest first


async def test_order_and_limit(db):
    cal = (await seed_calendars(db))["U"]
    series = await seed_series(
        db,
        cal,
        "FREQ=WEEKLY;BYDAY=WE",
        "2026-05-06T10:00",
        "2026-05-06T11:00",
        title="weekly",
        status="published",
    )
    late = await seed_event(db, cal, title="late", status="published", starts_at=utc(2026, 9, 1))
    soon = await seed_event(db, cal, title="soon", status="published", starts_at=utc(2026, 7, 4))
    got = await _search(db)
    # by the card's own start: the series is in progress at ``now`` (its next date is 07-01)
    assert [c.id for c in got] == [series.id, soon.id, late.id]
    assert [c.id for c in await _search(db, limit=2)] == [series.id, soon.id]


@pytest.mark.parametrize("limit", [0, 51, True, "5", None, 2.0])
async def test_limits(db, limit):
    with pytest.raises(ValueError, match="limit"):
        await _search(db, limit=limit)


async def test_a_pattern_must_be_a_str(db):
    with pytest.raises(ValueError, match="pattern"):
        await _search(db, pattern=b"x")  # type: ignore[arg-type]


async def test_bad_event_id(db):
    with pytest.raises(ValueError, match="event_id"):
        await contract.get_event_card(db, tenant_id="default", event_id="x")  # type: ignore[arg-type]
    assert await contract.get_event_card(db, tenant_id="default", event_id=uuid.uuid4()) is None


async def test_a_series_with_nothing_left_is_not_a_card_or_a_hit(db):
    cal = (await seed_calendars(db))["U"]
    done = await seed_series(
        db,
        cal,
        "FREQ=WEEKLY;COUNT=2",
        "2026-06-03T10:00",
        "2026-06-03T11:00",
        title="done",
        status="published",
    )
    assert await contract.get_event_card(db, tenant_id="default", event_id=done.id) is None
    assert await _search(db, upcoming_only=False) == []


def test_mounted():
    from sm_events.core.services import EventsServices

    bare = FastAPI()
    assert contract.mounted(bare) is False and contracts.mounted(bare) is False
    bare.state.sm_events = EventsServices(settings=None)
    assert contract.mounted(bare) is True


def test_contract_surface():
    assert contract.__all__ == [
        "MAX_EVENT_SEARCH_LIMIT",
        "EventCard",
        "get_event_card",
        "mounted",
        "search_events",
    ]
    assert contract.MAX_EVENT_SEARCH_LIMIT == 50
    assert contract.mounted is contracts.mounted
