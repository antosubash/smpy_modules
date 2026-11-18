"""``/api/events/events``: create, read, edit, trash, restore and the envelope."""

from __future__ import annotations

import pytest

from tests.support.events_http import (
    EV,
    MANAGER,
    OWNER,
    OWNER_PUB,
    SHARE_EDIT,
    SHARE_VIEW,
    STRANGER,
    VIEWER,
    cast,
    create,
    create_json,
    seed_event,
    stored,
)

WEEKLY = "FREQ=WEEKLY;BYDAY=WE"


async def test_create_read_update_round_trip(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal, venue_name="Hall", organiser="Org")
    assert made["revision"] == 1 and made["status"] == "draft" and made["locked"] is False
    assert made["start_local"] == "2026-07-01T10:00" and made["end_local"] == "2026-07-01T11:00"
    assert made["starts_at"].startswith("2026-07-01T08:00:00")  # CEST: UTC+2
    assert made["texts"]["en"]["slug"] == "concert" and made["uid"].endswith(
        "@simple-module-events"
    )
    assert made["can_write"] is True and made["can_publish"] is False
    assert made["overrides"] == [] and made["sub_events"] == [] and made["extra"] == {}
    got = await client.get(f"{EV}/{made['id']}", headers=OWNER)
    assert got.status_code == 200 and got.json() == made
    patched = await client.patch(
        f"{EV}/{made['id']}",
        json={
            "expected_revision": 1,
            "times": {
                "timezone": "Europe/Vienna",
                "start": "2026-07-02T09:30",
                "end": "2026-07-02T10:00",
            },
            "texts": {"en": {"title": "Renamed", "description": "<p onclick=x>hi</p>"}},
            "attendance_mode": "hybrid",
        },
        headers=OWNER,
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["revision"] == 2 and body["start_local"] == "2026-07-02T09:30"
    assert body["texts"]["en"]["description"] == "<p>hi</p>"
    assert body["texts"]["en"]["slug"] == "concert"  # a title change keeps the address
    assert body["attendance_mode"] == "hybrid" and body["venue_name"] == "Hall"


async def test_all_day_round_trip_uses_dates(client):
    cal = (await cast(client))["I"]
    made = await create(
        client, cal,
        times={
            "all_day": True,
            "timezone": "Europe/Vienna",
            "start": "2026-03-29",
            "end": "2026-03-29",
        },
    )  # fmt: skip
    assert (made["start_local"], made["end_local"]) == ("2026-03-29", "2026-03-29")
    assert made["starts_at"].startswith("2026-03-28T23:00:00")
    assert made["ends_at"].startswith("2026-03-29T22:00:00")


async def test_series_create_and_rule_normalised(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal, rrule="freq=weekly;byday=we")
    assert made["rrule"] == WEEKLY and made["recurrence_until"] is None
    finite = await create(client, cal, rrule="FREQ=DAILY;COUNT=3")
    assert finite["recurrence_until"].startswith("2026-07-03T09:00:00")


async def test_trash_and_restore_round_trip(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal)
    url = f"{EV}/{made['id']}"
    assert (await client.delete(f"{url}?expected_revision=1", headers=OWNER)).status_code == 204
    assert (
        await client.get(url, headers=OWNER)
    ).status_code == 404  # trashed: gone like a missing id
    back = await client.post(f"{url}/restore", json={"expected_revision": 2}, headers=OWNER)
    assert back.status_code == 200 and back.json()["revision"] == 3
    assert (await client.get(url, headers=OWNER)).status_code == 200


async def test_missing_expected_revision_is_a_validation_error(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal)
    assert (await client.delete(f"{EV}/{made['id']}", headers=OWNER)).status_code == 422
    assert (await client.patch(f"{EV}/{made['id']}", json={}, headers=OWNER)).status_code == 422


async def test_invalid_bodies_are_422(client):
    cal = (await cast(client))["I"]
    bad = [
        {"texts": {"en": {"title": "bad\nline"}}},
        {"texts": {"en": {"title": ""}}},
        {"venue_name": "x" * 201},
        {"online_url": "javascript:alert(1)"},
        {"image": "data:image/png;base64,AAAA"},
        {"registration_url": "/relative"},
        {"latitude": 91},
        {"longitude": -181},
        {"attendance_mode": "teleport"},
        {
            "times": {
                "timezone": "Mars/Base",
                "start": "2026-07-01T10:00",
                "end": "2026-07-01T11:00",
            }
        },
        {"organiser": "a‮b"},
    ]
    for extra in bad:
        got = await client.post(EV, json=create_json(cal, **extra), headers=OWNER)
        assert got.status_code == 422, extra
    ok = await client.post(
        EV,
        json=create_json(cal, online_url="https://meet.example/x", latitude=-90, longitude=180),
        headers=OWNER,
    )
    assert ok.status_code == 201


async def test_response_does_not_inherit_input_bounds(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal)

    from sm_events.models import EventText
    from sqlalchemy import update

    from tests.support.events_http import run

    async def overlong(db):
        await db.execute(update(EventText).values(title="two\nlines\u202e"))

    await run(client, overlong)
    got = await client.get(f"{EV}/{made['id']}", headers=OWNER)
    # a row the input rules would refuse (a newline, a direction mark) still renders
    assert got.status_code == 200 and got.json()["texts"]["en"]["title"] == "two\nlines\u202e"


async def test_stale_everywhere(client):
    cal = (await cast(client))["I"]
    pub = {**OWNER_PUB}
    # An event moved on to revision 3 by two edits, then every write quotes revision 1.
    made = await create(client, cal, headers=pub, rrule=WEEKLY)
    url = f"{EV}/{made['id']}"
    for rev in (1, 2):
        step = await client.patch(
            url, json={"expected_revision": rev, "venue_name": f"v{rev}"}, headers=pub
        )
        assert step.status_code == 200
    original = "2026-07-08T08:00:00Z"
    override = await client.post(
        f"{url}/overrides",
        json={"expected_revision": 3, "original_start": original, "kind": "skipped"},
        headers=pub,
    )
    assert override.status_code == 200 and override.json()["event_revision"] == 4
    old = 1
    calls = [
        ("PATCH", url, {"expected_revision": old, "venue_name": "x"}),
        ("DELETE", f"{url}?expected_revision={old}", None),
        ("POST", f"{url}/submit", {"expected_revision": old}),
        ("POST", f"{url}/withdraw", {"expected_revision": old}),
        ("POST", f"{url}/approve", {"expected_revision": old}),
        ("POST", f"{url}/reject", {"expected_revision": old, "note": "n"}),
        ("POST", f"{url}/unschedule", {"expected_revision": old}),
        ("POST", f"{url}/unpublish", {"expected_revision": old}),
        (
            "POST",
            f"{url}/overrides",
            {"expected_revision": old, "original_start": original, "kind": "cancelled"},
        ),
        ("DELETE", f"{url}/overrides/{override.json()['id']}?expected_revision={old}", None),
    ]
    for method, path, body in calls:
        got = await client.request(method, path, json=body, headers=pub)
        assert (got.status_code, got.json().get("code")) == (409, "stale"), (method, path, got.text)
        assert got.headers["x-current-revision"] == "4"
    assert (await stored(client, made["id"]))["revision"] == 4
    trashed = await client.delete(f"{url}?expected_revision=4", headers=pub)
    assert trashed.status_code == 204
    again = await client.post(f"{url}/restore", json={"expected_revision": 1}, headers=pub)
    assert (again.status_code, again.json()["code"]) == (409, "stale")


async def test_writes_need_csrf(csrf_client):
    from tests.support.events_http import cast as cast_calendars

    cal = (await cast_calendars(csrf_client))["I"]
    body = create_json(cal)
    refused = await csrf_client.post(EV, json=body, headers=OWNER)
    assert refused.status_code == 403 and "CSRF" in refused.json()["detail"]
    token = (await csrf_client.get("/token")).json()["token"]
    ok = await csrf_client.post(EV, json=body, headers={**OWNER, "X-CSRF-Token": token})
    assert ok.status_code == 201
    event_id = ok.json()["id"]
    for method, path, payload in (
        ("PATCH", f"{EV}/{event_id}", {"expected_revision": 1}),
        ("DELETE", f"{EV}/{event_id}?expected_revision=1", None),
        ("POST", f"{EV}/{event_id}/submit", {"expected_revision": 1}),
        ("POST", f"{EV}/{event_id}/restore", {"expected_revision": 1}),
        ("POST", f"{EV}/{event_id}/overrides", {}),
        ("POST", f"{EV}/{event_id}/approve", {"expected_revision": 1}),
    ):
        got = await csrf_client.request(method, path, json=payload, headers=OWNER)
        assert got.status_code == 403, (method, path)


async def test_anonymous_and_permissionless_are_refused(client):
    cal = (await cast(client))["U"]
    event = await seed_event(client, cal, status="published")
    from tests.support.app import as_user

    for headers in ({}, as_user("n")):  # nobody; signed in without events.view
        for method, path in (("GET", EV), ("GET", f"{EV}/{event['id']}"), ("POST", EV)):
            got = await client.request(
                method, path, json={} if method == "POST" else None, headers=headers
            )
            assert got.status_code in (401, 403), (method, path, got.status_code)


@pytest.mark.parametrize("who", [VIEWER, STRANGER, SHARE_VIEW, SHARE_EDIT, MANAGER])
async def test_unknown_event_is_the_same_404_for_everyone(client, who):
    import uuid

    missing = f"{EV}/{uuid.uuid4()}"
    got = await client.get(missing, headers=who)
    assert (got.status_code, got.json()) == (404, {"detail": "Not found", "code": "not_found"})
