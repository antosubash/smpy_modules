"""Availability: what a page may show (few seats left, the window as text) without raw counts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_events.models import Event
from sm_events.registration.availability import describe

from tests.registration.support import (
    NOW,
    one_off,
    public_calendar,
    taken,
)
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

LATER = NOW + timedelta(days=1)
AN_ID = "0b1d3f6e-5c1a-4f0e-9d3a-2b7c8e9f1a42"
"""A fixed uuid: parametrize ids must be the same in every xdist worker."""


async def ask(db, event, key=None, *, provider=PROVIDER_ID, target=KNOWN_TARGET, **kw):
    kw.setdefault("locale", "en")
    kw.setdefault("now", NOW)
    return await describe(
        db,
        tenant_id="default",
        event_id=event.id if isinstance(event, Event) else event,
        occurrence_key=key if key is not None else str(event.id),
        provider=provider,
        target=target,
        **kw,
    )


@pytest.fixture
async def cal(db):
    return await public_calendar(db)


@pytest.mark.parametrize(
    ("show", "capacity", "used", "few"),
    [
        (True, 10, 0, False),
        (True, 10, 7, False),
        (True, 10, 8, True),  # a fifth or less of the seats is left
        (True, 10, 9, True),
        (True, 10, 10, False),  # full is a state of its own
        (True, 3, 2, True),  # at least one seat counts
        (False, 10, 9, False),  # hidden seats: no count-derived state at all
        (False, 10, 8, False),
        (True, None, 50, False),
    ],
)
async def test_few_left_only_when_the_event_shows_seats(db, cal, show, capacity, used, few):
    event = await one_off(db, cal, registration_capacity=capacity, registration_show_seats=show)
    await taken(db, event, None, used)
    got = await ask(db, event)
    assert got.few_left is few
    assert not hasattr(got, "taken") and not hasattr(got, "capacity")  # no raw numbers returned
    if not show:
        assert got.seats_left is None


async def test_the_window_comes_with_text_in_the_events_zone_like_the_time_beside_it(db, cal):
    """The panel must not format the opening time in the visitor's own zone: it would disagree with
    the event time next to it. The text is built like the event's own time (zone label too)."""
    opens = datetime(2026, 6, 1, 4, 30, tzinfo=UTC)  # 06:30 in Vienna (summer time)
    event = await one_off(
        db,
        cal,
        registration_capacity=5,
        registration_opens_at=opens,
        registration_closes_at=opens + timedelta(days=2),
    )
    got = await ask(db, event, locale="en")
    assert got.opens_text and "6:30" in got.opens_text and "CEST" in got.opens_text
    assert got.closes_text and "CEST" in got.closes_text
    de = await ask(db, event, locale="de")
    assert "06:30" in de.opens_text and "Montag" in de.opens_text  # the reader's language
    plain = await one_off(db, cal)
    got = await ask(db, plain)
    assert (got.opens_text, got.closes_text) == (None, None)
