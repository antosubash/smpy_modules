"""The series-change preview needs the right to change the event: the overrides it
would orphan carry their notes, which only writers see."""

from __future__ import annotations

from tests.support.events_http import (
    EV,
    OWNER,
    OWNER_PUB,
    SHARE_EDIT,
    SHARE_VIEW,
    VIEWER,
    cast,
    seed_event,
)

WEEKLY = "FREQ=WEEKLY;BYDAY=WE"
PREVIEW = "/api/events/recurrence/preview"
TIMES = {"timezone": "Europe/Vienna", "start": "2026-07-01T10:00", "end": "2026-07-01T11:00"}


async def _noted_series(client, status):
    cal = (await cast(client))["I"]
    series = await seed_event(client, cal, status=status, rrule=WEEKLY)
    done = await client.post(
        f"{EV}/{series['id']}/overrides",
        json={
            "expected_revision": series["revision"],
            "original_start": "2026-07-08T08:00:00Z",
            "kind": "skipped",
            "note": "secret note",
        },
        headers=OWNER_PUB,
    )
    assert done.status_code in (200, 201), done.text
    return cal, series


CHANGED = {"timezone": "Europe/Vienna", "start": "2026-06-30T10:00", "end": "2026-06-30T11:00"}


async def _preview(client, series, headers, **extra):
    body = {"times": CHANGED, "rrule": "FREQ=WEEKLY;BYDAY=TU", "event_id": series["id"], **extra}
    return await client.post(PREVIEW, json=body, headers=headers)


async def test_preview_needs_the_write_right(client):
    _cal, series = await _noted_series(client, "published")
    for who in (VIEWER, SHARE_VIEW):
        got = await _preview(client, series, who)
        assert got.status_code == 403, who
        assert "orphaned" not in got.json() and "secret" not in got.text
    # an editor without events.publish gets what the PATCH gives on a published series
    patch = await client.patch(
        f"{EV}/{series['id']}", json={"expected_revision": 3, "rrule": None}, headers=OWNER
    )
    got = await _preview(client, series, OWNER)
    assert (got.status_code, got.json()["code"]) == (patch.status_code, patch.json()["code"])
    assert got.json()["code"] == "publish_required"
    ok = await _preview(client, series, OWNER_PUB)
    assert [o["note"] for o in ok.json()["orphaned"]] == ["secret note"]


async def test_preview_for_an_edit_share_holder_on_a_draft(client):
    _cal, series = await _noted_series(client, "draft")
    got = await _preview(client, series, SHARE_EDIT)
    assert got.status_code == 200, got.text
    assert [o["note"] for o in got.json()["orphaned"]] == ["secret note"]


async def test_preview_of_a_new_event_needs_write_on_the_calendar(client):
    cal = (await cast(client))["I"]
    body = {"times": TIMES, "rrule": WEEKLY, "calendar_id": cal}
    assert (await client.post(PREVIEW, json=body, headers=VIEWER)).status_code == 403
    assert (await client.post(PREVIEW, json=body, headers=OWNER)).status_code == 200
    unknown = {**body, "calendar_id": "00000000-0000-0000-0000-000000000000"}
    assert (await client.post(PREVIEW, json=unknown, headers=OWNER)).status_code == 404
