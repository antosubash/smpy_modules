"""Workflow, history, overrides, the preview and the bus, over HTTP."""

from __future__ import annotations

from simple_module_core.events import Event as BusEvent
from sm_events.contracts import events as contract

from tests.support.events_http import (
    EV,
    OWNER,
    OWNER_PUB,
    VIEWER,
    cast,
    create,
    seed_event,
)

WEEKLY = "FREQ=WEEKLY;BYDAY=WE"
PREVIEW = "/api/events/recurrence/preview"
TIMES = {"timezone": "Europe/Vienna", "start": "2026-07-01T10:00", "end": "2026-07-01T11:00"}


async def post(client, event_id, action, body, headers=OWNER_PUB):
    return await client.post(f"{EV}/{event_id}/{action}", json=body, headers=headers)


async def test_review_cycle_over_http(client):
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    eid = event["id"]
    sub = await post(client, eid, "submit", {"expected_revision": 1}, OWNER)
    assert (
        sub.status_code == 200
        and sub.json()["status"] == "in_review"
        and sub.json()["revision"] == 2
    )
    rej = await post(client, eid, "reject", {"expected_revision": 2, "note": "too vague"})
    assert rej.json()["status"] == "draft"
    await post(client, eid, "submit", {"expected_revision": 3}, OWNER)
    sched = await post(
        client, eid, "approve", {"expected_revision": 4, "publish_at_local": "2099-01-01T10:00"}
    )
    body = sched.json()
    assert (body["status"], body["scheduled"], body["locked"]) == ("in_review", True, True)
    assert body["publish_at_local"] == "2099-01-01T10:00" and body["publish_at"].startswith(
        "2099-01-01T09:00"
    )
    # a scheduled event is locked for a writer without publish
    locked = await client.patch(
        f"{EV}/{eid}", json={"expected_revision": 5, "venue_name": "x"}, headers=OWNER
    )
    assert (locked.status_code, locked.json()["code"]) == (403, "publish_required")
    un = await post(client, eid, "unschedule", {"expected_revision": 5})
    assert un.json()["scheduled"] is False
    live = await post(client, eid, "approve", {"expected_revision": 6})
    assert live.json()["status"] == "published" and live.json()["published_at"]
    down = await post(client, eid, "unpublish", {"expected_revision": 7})
    assert down.json()["status"] == "draft" and down.json()["published_at"]


async def test_reject_needs_a_note(client):
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    await post(client, event["id"], "submit", {"expected_revision": 1}, OWNER)
    for bad in ({"expected_revision": 2}, {"expected_revision": 2, "note": "  "}):
        assert (await post(client, event["id"], "reject", bad)).status_code == 422


async def test_revisions_api(client):
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    eid = event["id"]
    await client.patch(
        f"{EV}/{eid}", json={"expected_revision": 1, "venue_name": "Hall"}, headers=OWNER
    )
    await post(client, eid, "submit", {"expected_revision": 2}, OWNER)
    await post(client, eid, "reject", {"expected_revision": 3, "note": "no"})
    listed = await client.get(f"{EV}/{eid}/revisions", headers=OWNER)
    rows = listed.json()
    assert [r["number"] for r in rows] == [4, 3, 2, 1]
    assert [r["action"] for r in rows] == ["rejected", "submitted", "updated", "created"]
    assert (
        all("snapshot" not in r for r in rows)
        and rows[0]["note"] == "no"
        and rows[0]["actor"] == "o"
    )
    one = await client.get(f"{EV}/{eid}/revisions/2", headers=OWNER)
    assert one.json()["snapshot"]["venue_name"] == "Hall" and one.json()["action"] == "updated"
    assert (await client.get(f"{EV}/{eid}/revisions/99", headers=OWNER)).status_code == 404


async def test_history_is_for_writers_only(client):
    cal = (await cast(client))["I"]
    event = await seed_event(client, cal, status="published")
    got = await client.get(f"{EV}/{event['id']}/revisions", headers=VIEWER)
    assert (got.status_code, got.json()["code"]) == (403, "forbidden")


async def test_overrides_over_http(client):
    cal = (await cast(client))["I"]
    series = await create(client, cal, rrule=WEEKLY)
    sid = series["id"]
    moved = await client.post(
        f"{EV}/{sid}/overrides",
        json={
            "expected_revision": 1, "original_start": "2026-07-08T08:00:00Z", "kind": "moved",
            "start": "2026-07-09T11:00", "end": "2026-07-09T12:00", "note": "stage change",
        },
        headers=OWNER,
    )  # fmt: skip
    body = moved.json()
    assert moved.status_code == 200 and body["event_revision"] == 2
    assert (body["start_local"], body["end_local"]) == ("2026-07-09T11:00", "2026-07-09T12:00")
    shown = (await client.get(f"{EV}/{sid}", headers=OWNER)).json()
    assert [o["id"] for o in shown["overrides"]] == [body["id"]] and shown["revision"] == 2
    extra = await client.post(
        f"{EV}/{sid}/overrides",
        json={
            "expected_revision": 2,
            "original_start": "2026-07-15T08:00:00Z",
            "kind": "skipped",
            "title": "no",
        },
        headers=OWNER,
    )
    assert extra.status_code == 422
    cleared = await client.delete(
        f"{EV}/{sid}/overrides/{body['id']}?expected_revision=2", headers=OWNER
    )
    assert cleared.status_code == 204
    assert (await client.get(f"{EV}/{sid}", headers=OWNER)).json()["overrides"] == []
    missing = await client.delete(f"{EV}/{sid}/overrides/999?expected_revision=3", headers=OWNER)
    assert (missing.status_code, missing.json()["code"]) == (404, "not_found")


async def test_a_viewer_of_a_published_series_sees_no_override_notes(client):
    cal = (await cast(client))["I"]
    series = await seed_event(client, cal, status="published", rrule=WEEKLY)
    skip = await client.post(
        f"{EV}/{series['id']}/overrides",
        json={
            "expected_revision": 1,
            "original_start": "2026-07-08T08:00:00Z",
            "kind": "cancelled",
            "note": "internal",
        },
        headers=OWNER_PUB,
    )
    assert skip.status_code == 200
    as_viewer = (await client.get(f"{EV}/{series['id']}", headers=VIEWER)).json()
    assert [(o["kind"], o["note"]) for o in as_viewer["overrides"]] == [("cancelled", None)]
    as_owner = (await client.get(f"{EV}/{series['id']}", headers=OWNER)).json()
    assert as_owner["overrides"][0]["note"] == "internal"


async def test_preview_api(client):
    got = await client.post(
        PREVIEW,
        json={"times": TIMES, "rrule": WEEKLY, "count": 3, "after": "2026-07-02T00:00:00Z"},
        headers=OWNER,
    )
    assert got.status_code == 200, got.text
    body = got.json()
    assert [o["start_local"] for o in body["occurrences"]] == [
        "2026-07-08T10:00", "2026-07-15T10:00", "2026-07-22T10:00",
    ]  # fmt: skip
    assert body["orphaned"] == [] and body["recurrence_until"] is None
    for bad in ({"times": TIMES, "count": 51}, {"times": TIMES, "after": "2026-07-02T00:00:00"}):
        assert (await client.post(PREVIEW, json=bad, headers=OWNER)).status_code == 422
    nope = await client.post(PREVIEW, json={"times": TIMES, "rrule": "FREQ=HOURLY"}, headers=OWNER)
    assert (nope.status_code, nope.json()["code"]) == (422, "rrule_frequency_refused")


async def test_preview_reports_orphans_and_hides_invisible_events(client):
    cal = (await cast(client))["I"]
    series = await create(client, cal, rrule=WEEKLY)
    await client.post(
        f"{EV}/{series['id']}/overrides",
        json={"expected_revision": 1, "original_start": "2026-07-08T08:00:00Z", "kind": "skipped"},
        headers=OWNER,
    )
    changed = {"timezone": "Europe/Vienna", "start": "2026-06-30T10:00", "end": "2026-06-30T11:00"}
    got = await client.post(
        PREVIEW,
        json={"times": changed, "rrule": "FREQ=WEEKLY;BYDAY=TU", "event_id": series["id"]},
        headers=OWNER,
    )
    assert [o["kind"] for o in got.json()["orphaned"]] == ["skipped"]
    draft = await create(client, cal)  # a draft: a viewer cannot see it
    hidden = await client.post(
        PREVIEW, json={"times": TIMES, "event_id": draft["id"]}, headers=VIEWER
    )
    assert (hidden.status_code, hidden.json()) == (
        404,
        {"detail": "Not found", "code": "not_found"},
    )


class _Seen:
    def __init__(self, app) -> None:
        self.events: list[BusEvent] = []
        for cls in (
            contract.EventPublished,
            contract.EventRescheduled,
            contract.EventCancelled,
            contract.EventDeleted,
        ):
            app.state.sm.event_bus.subscribe(cls, self._on)

    async def _on(self, event):
        self.events.append(event)


async def test_bus_events_after_commit_http(client):
    seen = _Seen(client.app)
    cal = (await cast(client))["I"]
    live = await seed_event(client, cal, status="published")
    eid = live["id"]
    refused = await client.patch(
        f"{EV}/{eid}",
        json={
            "expected_revision": 1,
            "times": {**TIMES, "start": "2026-07-05T10:00", "end": "2026-07-05T11:00"},
        },
        headers=OWNER,
    )
    assert (
        refused.status_code == 403 and seen.events == []
    )  # no publish: nothing written, nothing said
    stale = await client.patch(
        f"{EV}/{eid}", json={"expected_revision": 5, "cancelled": True}, headers=OWNER_PUB
    )
    assert stale.status_code == 409 and seen.events == []
    ok = await client.patch(
        f"{EV}/{eid}",
        json={
            "expected_revision": 1,
            "times": {**TIMES, "start": "2026-07-05T10:00", "end": "2026-07-05T11:00"},
        },
        headers=OWNER_PUB,
    )
    assert ok.status_code == 200
    (got,) = seen.events
    assert isinstance(got, contract.EventRescheduled) and str(got.event_id) == eid
    assert got.tenant_id == "default" and got.original_start is None
    cancelled = await client.patch(
        f"{EV}/{eid}", json={"expected_revision": 2, "cancelled": True}, headers=OWNER_PUB
    )
    assert cancelled.status_code == 200
    deleted = await client.delete(f"{EV}/{eid}?expected_revision=3", headers=OWNER_PUB)
    assert deleted.status_code == 204
    assert [type(e).__name__ for e in seen.events] == [
        "EventRescheduled",
        "EventCancelled",
        "EventDeleted",
    ]


async def test_publish_over_http_announces_after_commit(client):
    seen = _Seen(client.app)
    cal = (await cast(client))["I"]
    draft = await create(client, cal)
    await post(client, draft["id"], "submit", {"expected_revision": 1}, OWNER)
    assert seen.events == []
    await post(client, draft["id"], "approve", {"expected_revision": 2})
    (got,) = seen.events
    assert isinstance(got, contract.EventPublished) and str(got.calendar_id) == cal
