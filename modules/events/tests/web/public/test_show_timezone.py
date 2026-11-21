"""When a public list names an item's time zone: one rule, shared by the index, a calendar's page,
the 404's suggestions and the blocks.

The reference zone is the one zone every calendar the list draws from shares. A timed item whose
zone differs from it is labelled; when the calendars differ among themselves there is no
reference, so every timed item is labelled. An all-day item is dates and never is.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Visibility

from tests.support.calendars import seed_event
from tests.support.public import INERTIA

UPCOMING = f"{constants.PUBLIC_BLOCKS_API}/upcoming?count=20"
VIENNA, NEW_YORK = "Europe/Vienna", "America/New_York"


def _when(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 4, day, hour, tzinfo=UTC)


async def _cal(db, slug: str, zone: str) -> Calendar:
    cal = Calendar(
        slug=slug, name=slug.title(), owner_id="o", visibility=Visibility.PUBLIC,
        default_timezone=zone,
    )  # fmt: skip
    db.add(cal)
    await db.flush()
    return cal


async def _seed(client, spec):
    """``spec``: {calendar slug: zone}, then events as (calendar, title, own zone, all_day)."""
    calendars, events = spec
    with tenant_scope("default"):
        async with client.db_state.session_factory() as db:
            made = {slug: await _cal(db, slug, zone) for slug, zone in calendars.items()}
            for i, (slug, title, zone, all_day) in enumerate(events):
                await seed_event(
                    db, made[slug], title=title, slug=title.lower(), status="published",
                    starts_at=_when(10 + i), timezone=zone, all_day=all_day,
                )  # fmt: skip
            await db.commit()


async def _labelled(client, query: str = "") -> dict[str, bool]:
    got = (await client.get(f"{UPCOMING}{query}")).json()["items"]
    return {i["title"]: i["show_timezone"] for i in got}


async def test_one_calendar_labels_only_what_differs_from_it(public_locales_client):
    await _seed(
        public_locales_client,
        (
            {"vienna": VIENNA},
            [
                ("vienna", "Own", VIENNA, False),
                (
                    "vienna",
                    "Abroad",
                    NEW_YORK,
                    False,
                ),  # an event whose zone differs from its calendar's
                ("vienna", "Dates", NEW_YORK, True),  # all-day: never
            ],
        ),
    )
    assert await _labelled(public_locales_client) == {"Own": False, "Abroad": True, "Dates": False}


async def test_two_calendars_in_one_zone_share_the_reference(public_locales_client):
    await _seed(
        public_locales_client,
        (
            {"north": VIENNA, "south": VIENNA},
            [
                ("north", "A", VIENNA, False),
                ("south", "B", VIENNA, False),
                ("south", "C", NEW_YORK, False),
            ],
        ),
    )
    assert await _labelled(public_locales_client) == {"A": False, "B": False, "C": True}


async def test_calendars_in_different_zones_label_every_timed_item(public_locales_client):
    await _seed(
        public_locales_client,
        (
            {"vienna": VIENNA, "newyork": NEW_YORK},
            [
                ("vienna", "Transatlantic call", VIENNA, False),
                ("newyork", "Studio hour", NEW_YORK, False),
                ("newyork", "Gallery day", NEW_YORK, True),
            ],
        ),
    )
    both = await _labelled(public_locales_client)
    assert both == {"Transatlantic call": True, "Studio hour": True, "Gallery day": False}
    # Choosing one of the calendars makes it the reference again.
    only = await _labelled(public_locales_client, "&calendar=newyork")
    assert only == {"Studio hour": False, "Gallery day": False}


async def test_the_index_and_the_blocks_follow_the_same_rule(public_locales_client):
    await _seed(
        public_locales_client,
        (
            {"vienna": VIENNA, "newyork": NEW_YORK},
            [("vienna", "One", VIENNA, False), ("newyork", "Two", NEW_YORK, False)],
        ),
    )
    index = (await public_locales_client.get("/events/", headers=INERTIA)).json()["props"]
    items = {i["title"]: i["show_timezone"] for g in index["groups"] for i in g["items"]}
    assert items == {"One": True, "Two": True}
    page = (await public_locales_client.get("/events/c/newyork", headers=INERTIA)).json()["props"]
    one = {i["title"]: i["show_timezone"] for g in page["groups"] for i in g["items"]}
    assert one == {"Two": False}


@pytest.mark.parametrize("zones", [(), (VIENNA,)])
async def test_no_calendar_or_one_calendar_has_a_reference_or_nothing_to_label(
    public_locales_client, zones
):
    assert await _labelled(public_locales_client) == {}
