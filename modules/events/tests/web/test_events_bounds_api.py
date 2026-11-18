"""Edge values in a path or a body are a 4xx, never a 500 (SQLite and Postgres)."""

from __future__ import annotations

import pytest

from tests.support.events_http import EV, OWNER, cast, create

WEEKLY = "FREQ=WEEKLY;BYDAY=WE"


@pytest.mark.parametrize(
    "original",
    [
        "9999-12-31T23:59:59.999999Z",
        "9000-01-01T00:00:00Z",
        "0001-01-01T00:00:00Z",
        "1899-12-31T23:59:59Z",
    ],
)
async def test_an_original_start_outside_a_sane_range_is_422(client, original):
    series = await create(client, (await cast(client))["I"], rrule=WEEKLY)
    got = await client.post(
        f"{EV}/{series['id']}/overrides",
        json={"expected_revision": 1, "original_start": original, "kind": "skipped"},
        headers=OWNER,
    )
    assert got.status_code == 422, got.text


async def test_a_sane_original_start_that_is_no_occurrence_is_still_422_not_an_error(client):
    series = await create(client, (await cast(client))["I"], rrule=WEEKLY)
    got = await client.post(
        f"{EV}/{series['id']}/overrides",
        json={"expected_revision": 1, "original_start": "2999-01-01T00:00:00Z", "kind": "skipped"},
        headers=OWNER,
    )
    assert (got.status_code, got.json()["code"]) == (422, "not_an_occurrence")


@pytest.mark.parametrize("number", ["0", "-1", "2147483648", "99999999999999999999"])
async def test_a_revision_number_out_of_range_is_4xx(client, number):
    series = await create(client, (await cast(client))["I"])
    got = await client.get(f"{EV}/{series['id']}/revisions/{number}", headers=OWNER)
    assert got.status_code in (404, 422), got.text


@pytest.mark.parametrize("override_id", ["0", "2147483648", "99999999999999999999"])
async def test_an_override_id_out_of_range_is_4xx(client, override_id):
    series = await create(client, (await cast(client))["I"], rrule=WEEKLY)
    got = await client.delete(
        f"{EV}/{series['id']}/overrides/{override_id}?expected_revision=1", headers=OWNER
    )
    assert got.status_code in (404, 422), got.text


async def test_the_largest_valid_ids_are_a_404(client):
    series = await create(client, (await cast(client))["I"], rrule=WEEKLY)
    top = 2**31 - 1
    for path in (f"revisions/{top}",):
        assert (await client.get(f"{EV}/{series['id']}/{path}", headers=OWNER)).status_code == 404
    got = await client.delete(
        f"{EV}/{series['id']}/overrides/{top}?expected_revision=1", headers=OWNER
    )
    assert got.status_code == 404


async def test_a_preview_after_outside_a_sane_range_is_422(client):
    got = await client.post(
        "/api/events/recurrence/preview",
        json={
            "rrule": WEEKLY,
            "after": "9999-12-31T23:59:59.999999Z",
            "times": {
                "timezone": "Europe/Vienna",
                "start": "2026-07-01T10:00",
                "end": "2026-07-01T11:00",
            },
        },
        headers=OWNER,
    )
    assert got.status_code == 422, got.text
