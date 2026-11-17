"""Every event route, asked by a stranger, a view-share holder, an edit-share
holder, an owner without publish, a manager and an owner with publish."""

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
    cast,
    seed_event,
)

PRINCIPALS = {
    "stranger": STRANGER,  # signed in, no share, not the owner: sees nothing of a private calendar
    "view-share": SHARE_VIEW,
    "edit-share": SHARE_EDIT,
    "owner": OWNER,  # owner without events.publish
    "manager": MANAGER,  # events.manage without publish
    "publisher": OWNER_PUB,
}
WRITERS = {"edit-share", "owner", "manager", "publisher"}
SUCCESS = {
    "get": 200, "patch": 200, "delete": 204, "submit": 200, "approve": 200, "unpublish": 200,
    "revisions": 200, "revision": 200, "override": 200, "preview": 200,
}  # fmt: skip


def request_for(route: str, event_id: str) -> tuple[str, str, dict | None]:
    url = f"{EV}/{event_id}"
    return {
        "get": ("GET", url, None),
        "patch": ("PATCH", url, {"expected_revision": 1, "venue_name": "x"}),
        "delete": ("DELETE", f"{url}?expected_revision=1", None),
        "submit": ("POST", f"{url}/submit", {"expected_revision": 1}),
        "approve": ("POST", f"{url}/approve", {"expected_revision": 1}),
        "unpublish": ("POST", f"{url}/unpublish", {"expected_revision": 1}),
        "revisions": ("GET", f"{url}/revisions", None),
        "revision": ("GET", f"{url}/revisions/1", None),
        "override": (
            "POST",
            f"{url}/overrides",
            {"expected_revision": 1, "original_start": "2026-07-08T08:00:00Z", "kind": "skipped"},
        ),
        "preview": (
            "POST",
            "/api/events/recurrence/preview",
            {
                "event_id": event_id,
                "rrule": "FREQ=WEEKLY;BYDAY=WE",
                "times": {
                    "timezone": "Europe/Vienna",
                    "start": "2026-07-01T10:00",
                    "end": "2026-07-01T11:00",
                },
            },
        ),
    }[route]


def expected(route: str, state: str, who: str) -> tuple[int, str | None]:
    """What the rules say, stated once: a calendar or draft the caller cannot see is
    404; a visible event the caller cannot write is 403 ``forbidden``; a locked
    event (published, or an action that publishes) needs ``events.publish``."""
    live = state == "published"
    if who == "stranger":
        return 404, "not_found"
    if route == "get":
        return (404, "not_found") if not live and who == "view-share" else (SUCCESS[route], None)
    if who == "view-share":
        return (403, "forbidden") if live else (404, "not_found")
    if route in ("revisions", "revision"):
        return SUCCESS[route], None
    needs_publish = live or route in ("approve", "unpublish")
    if needs_publish and who != "publisher":
        return 403, "publish_required"
    return SUCCESS[route], None


CASES = [
    (route, state)
    for state in ("draft", "published")
    for route in (
        "get", "patch", "delete", "revisions", "revision", "override", "preview",
        *(("submit", "approve") if state == "draft" else ("unpublish",)),
    )
]  # fmt: skip


@pytest.mark.parametrize("who", PRINCIPALS)
@pytest.mark.parametrize(("route", "state"), CASES)
async def test_route_matrix(client, route, state, who):
    calendar = (await cast(client))["P"]
    event = await seed_event(client, calendar, status=state, rrule="FREQ=WEEKLY;BYDAY=WE")
    method, path, body = request_for(route, event["id"])
    got = await client.request(method, path, json=body, headers=PRINCIPALS[who])
    status, code = expected(route, state, who)
    assert got.status_code == status, (route, state, who, got.text)
    if code is not None:
        assert got.json() == {"detail": got.json()["detail"], "code": code}
        if code == "not_found":  # the same body as an id that never existed
            assert got.json() == {"detail": "Not found", "code": "not_found"}


async def test_a_refused_write_changes_nothing(client):
    from tests.support.events_http import stored

    calendar = (await cast(client))["P"]
    event = await seed_event(client, calendar, status="published")
    for route in ("patch", "delete", "unpublish"):
        method, path, body = request_for(route, event["id"])
        got = await client.request(method, path, json=body, headers=SHARE_EDIT)
        assert (got.status_code, got.json()["code"]) == (403, "publish_required")
    assert (await stored(client, event["id"])) == {
        "revision": 1,
        "status": "published",
        "is_deleted": False,
    }
    history = await client.get(f"{EV}/{event['id']}/revisions", headers=OWNER_PUB)
    assert [r["action"] for r in history.json()] == ["created"]
