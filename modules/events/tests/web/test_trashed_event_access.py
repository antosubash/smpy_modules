"""A trashed event is a 404 for everyone who could not restore it, on every route."""

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
    seed_event,
    stored,
)
from tests.web.test_events_access import request_for

NOT_FOUND = {"detail": "Not found", "code": "not_found"}
PRINCIPALS = {
    "stranger": STRANGER,
    "viewer": VIEWER,
    "view-share": SHARE_VIEW,
    "edit-share": SHARE_EDIT,
    "owner": OWNER,
    "manager": MANAGER,
    "publisher": OWNER_PUB,
}
ROUTES = (
    "get", "patch", "delete", "revisions", "revision", "override", "preview", "submit",
    "approve", "unpublish",
)  # fmt: skip


async def trashed(client, state):
    cal = (await cast(client))["I"]
    event = await seed_event(client, cal, status=state, rrule="FREQ=WEEKLY;BYDAY=WE")
    gone = await client.delete(
        f"{EV}/{event['id']}?expected_revision={event['revision']}", headers=OWNER_PUB
    )
    assert gone.status_code == 204, gone.text
    return event["id"], (await stored(client, event["id"]))["revision"]


@pytest.mark.parametrize("state", ["draft", "published"])
@pytest.mark.parametrize("who", PRINCIPALS)
async def test_restore_of_a_trashed_event(client, state, who):
    event_id, revision = await trashed(client, state)
    got = await client.post(
        f"{EV}/{event_id}/restore", json={"expected_revision": revision}, headers=PRINCIPALS[who]
    )
    writes = who in {
        "stranger",
        "edit-share",
        "owner",
        "manager",
        "publisher",
    }  # events.edit on an internal calendar
    if not writes:
        assert (got.status_code, got.json()) == (404, NOT_FOUND), (who, state, got.text)
    elif state == "published" and who != "publisher":
        assert (got.status_code, got.json()["code"]) == (403, "publish_required")
    else:
        assert got.status_code == 200, (who, state, got.text)


@pytest.mark.parametrize("state", ["draft", "published"])
@pytest.mark.parametrize("who", PRINCIPALS)
@pytest.mark.parametrize("route", ROUTES)
async def test_every_other_route_answers_a_trashed_event_like_a_missing_one(
    client, route, who, state
):
    event_id, revision = await trashed(client, state)
    method, path, body = request_for(route, event_id)
    if body and "expected_revision" in body:
        body = {**body, "expected_revision": revision}
    got = await client.request(
        method,
        path.replace("expected_revision=1", f"expected_revision={revision}"),
        json=body,
        headers=PRINCIPALS[who],
    )
    assert (got.status_code, got.json()) == (404, NOT_FOUND), (route, who, state, got.text)
