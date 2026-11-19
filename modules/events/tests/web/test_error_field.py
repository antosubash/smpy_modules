"""A refusal that belongs to one input names it in the body's ``field``; every other
refusal keeps exactly ``{"detail", "code"}``."""

from __future__ import annotations

import pytest
from sm_events.calendar.times import to_span
from sm_events.core import constants
from sm_events.core.errors import InvalidTimes

from tests.support.events_http import EV, OWNER, OWNER_PUB, cast, create, create_json

GAP = "2026-03-29T02:30"
VIENNA = "Europe/Vienna"


def times(start: str, end: str) -> dict:
    return {"timezone": VIENNA, "start": start, "end": end}


@pytest.mark.parametrize(
    ("start", "end", "code", "field"),
    [
        (GAP, "2026-03-29T04:00", "invalid_local_time", "times.start"),
        ("2026-03-29T01:00", GAP, "invalid_local_time", "times.end"),
        ("2026-07-01T10:00", "2026-07-01T09:00", "end_before_start", "times.end"),
        ("2026-07-01T10:00", "2028-07-01T09:00", "duration_too_long", "times.end"),
    ],
)
async def test_a_time_refusal_names_start_or_end(locales_client, start, end, code, field):
    cal = (await cast(locales_client))["I"]
    got = await locales_client.post(
        EV, json=create_json(cal, times=times(start, end)), headers=OWNER
    )
    assert (got.status_code, got.json()["code"], got.json()["field"]) == (422, code, field)
    assert set(got.json()) == {"detail", "code", "field"}


async def test_slug_taken_names_the_locale_that_failed(locales_client):
    cal = (await cast(locales_client))["I"]
    await create(
        locales_client, cal, texts={"en": {"title": "A"}, "de": {"title": "A", "slug": "x"}}
    )
    body = create_json(
        cal,
        texts={"en": {"title": "B", "slug": "fresh"}, "de": {"title": "B", "slug": "x"}},
    )
    got = await locales_client.post(EV, json=body, headers=OWNER)
    assert (got.status_code, got.json()["code"]) == (409, "slug_taken")
    assert got.json()["field"] == "texts.de.slug"
    assert set(got.json()) == {"detail", "code", "field"}


async def test_description_too_long_names_its_locale(locales_client):
    cal = (await cast(locales_client))["I"]
    big = "x" * (constants.DESCRIPTION_RAW_MAX + 1)
    body = create_json(cal, texts={"en": {"title": "A"}, "de": {"title": "B", "description": big}})
    got = await locales_client.post(EV, json=body, headers=OWNER)
    assert (got.status_code, got.json()["code"]) == (422, "description_too_long")
    assert got.json()["field"] == "texts.de.description"


async def test_a_bad_publish_time_names_its_input(locales_client):
    cal = (await cast(locales_client))["I"]
    event = await create(locales_client, cal)
    got = await locales_client.post(
        f"{EV}/{event['id']}/approve",
        json={"expected_revision": event["revision"], "publish_at_local": "2027-03-28T02:30"},
        headers=OWNER_PUB,
    )
    assert (got.status_code, got.json()["code"]) == (422, "invalid_local_time")
    assert got.json()["field"] == "publish_at_local"


async def test_a_refusal_without_a_field_sends_no_header(locales_client):
    cal = (await cast(locales_client))["I"]
    got = await locales_client.post(EV, json=create_json(cal, rrule="FREQ=HOURLY"), headers=OWNER)
    assert got.status_code == 422
    assert set(got.json()) == {"detail", "code"}


def test_override_times_name_the_overrides_own_fields():
    with pytest.raises(InvalidTimes) as caught:
        to_span(
            all_day=False,
            timezone=VIENNA,
            start="2026-07-01T10:00",
            end=GAP,
            recurring=True,
            fields=("start", "end"),
        )
    assert caught.value.field == "end"
