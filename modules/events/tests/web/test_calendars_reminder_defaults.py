"""A calendar's default reminder lead times (PR 8): who sets them, and what is accepted."""

from __future__ import annotations

import pytest
from sm_events.core.constants import reminders_limits as limits

from tests.support.access import grant
from tests.support.calendars import BASE, OWNER, SE, SV, VIEWER, make


async def _patch(client, cid, body, headers=OWNER):
    return await client.patch(f"{BASE}/{cid}", json=body, headers=headers)


async def test_reminder_defaults_round_trip(client):
    made = await make(client)
    cid = made["id"]
    assert made["default_reminder_minutes"] is None
    got = await _patch(client, cid, {"default_reminder_minutes": [60, 15]})
    assert got.status_code == 200, got.text
    assert got.json()["default_reminder_minutes"] == [15, 60]  # sorted
    assert (await client.get(f"{BASE}/{cid}", headers=OWNER)).json()[
        "default_reminder_minutes"
    ] == [15, 60]
    # Another field's PATCH leaves it alone; an explicit null goes back to the install default.
    assert (await _patch(client, cid, {"name": "Renamed"})).json()["default_reminder_minutes"] == [
        15,
        60,
    ]
    assert (await _patch(client, cid, {"default_reminder_minutes": None})).json()[
        "default_reminder_minutes"
    ] is None
    # An empty list is a choice of its own: "preselect nothing here".
    assert (await _patch(client, cid, {"default_reminder_minutes": []})).json()[
        "default_reminder_minutes"
    ] == []


@pytest.mark.parametrize(
    "value",
    [[30], [0], [-60], [limits.MAX_LEAD_MINUTES + 1], [60, 60], [15, 60, 1440, 10080, 15]],
)
async def test_reminder_defaults_invalid_lead_422(client, value):
    cid = (await make(client))["id"]
    got = await _patch(client, cid, {"default_reminder_minutes": value})
    assert got.status_code == 422, got.text
    assert got.json()["code"] == "invalid_lead"
    assert set(got.json()) == {"detail", "code"}
    # Nothing was stored.
    assert (await client.get(f"{BASE}/{cid}", headers=OWNER)).json()[
        "default_reminder_minutes"
    ] is None


async def test_every_lead_is_accepted_at_the_edge(client):
    cid = (await make(client))["id"]
    got = await _patch(client, cid, {"default_reminder_minutes": list(limits.REMINDER_LEADS)})
    assert got.status_code == 200
    assert got.json()["default_reminder_minutes"] == list(limits.REMINDER_LEADS)


@pytest.mark.parametrize("value", ["60", 60, [True], ["60"], [60.5], {"a": 1}])
async def test_reminder_defaults_wrong_shape_is_422(client, value):
    cid = (await make(client))["id"]
    assert (await _patch(client, cid, {"default_reminder_minutes": value})).status_code == 422


async def test_a_huge_list_is_refused_without_being_walked(client):
    cid = (await make(client))["id"]
    got = await _patch(client, cid, {"default_reminder_minutes": [60] * 5000})
    assert got.status_code == 422


async def test_only_those_who_may_edit_the_calendar_set_them(client):
    cid = (await make(client))["id"]
    await grant(client, cid, "sv", "view")
    await grant(client, cid, "se", "edit")
    body = {"default_reminder_minutes": [15]}
    assert (await _patch(client, cid, body, SV)).status_code == 403
    assert (await _patch(client, cid, body, VIEWER)).status_code == 404  # cannot even see it
    assert (await _patch(client, cid, body, SE)).status_code == 200
