"""``GET /api/events/events``: filters, paging, the trash and tenant isolation."""

from __future__ import annotations

import pytest
from sm_events.models import Category

from tests.support.events_http import (
    EV,
    MANAGER,
    OWNER,
    OWNER_PUB,
    STRANGER,
    VIEWER,
    cast,
    create,
    run,
    seed_event,
)

BASE = "/api/events"


def ids(got) -> list[str]:
    assert got.status_code == 200, got.text
    return [i["id"] for i in got.json()["items"]]


async def test_list_filters_and_paging(locales_client):
    client = locales_client
    cals = await cast(client)
    cal = cals["I"]

    async def category(db):
        row = Category(slug="music", names={"en": "Music"})
        db.add(row)
        await db.flush()
        return str(row.id)

    cat = await run(client, category)
    july = await create(client, cal, texts={"en": {"title": "Alpha"}, "de": {"title": "Konzert"}})
    aug = await seed_event(client, cal, status="published", category_id=cat)
    series = await create(
        client, cal, rrule="FREQ=WEEKLY;BYDAY=WE", texts={"en": {"title": "Weekly"}}
    )
    other = await seed_event(client, cals["U"], status="published")
    # the August event: move it, then publish through the service helper above
    patched = await client.patch(
        f"{EV}/{aug['id']}",
        json={
            "expected_revision": 1,
            "times": {"timezone": "UTC", "start": "2026-08-05T10:00", "end": "2026-08-05T11:00"},
        },
        headers=OWNER_PUB,
    )
    assert patched.status_code == 200, patched.text

    everything = await client.get(EV, headers=OWNER)
    assert everything.json()["total"] == 4 and everything.json()["page"] == 1
    tied = sorted([july["id"], series["id"], other["id"]])  # the same instant: then by id
    assert ids(everything) == [*tied, aug["id"]]
    assert ids(await client.get(f"{EV}?status=published", headers=OWNER)) == [
        other["id"],
        aug["id"],
    ]
    assert set(ids(await client.get(f"{EV}?status=draft&calendar={cal}", headers=OWNER))) == {
        july["id"],
        series["id"],
    }
    assert ids(await client.get(f"{EV}?category={cat}", headers=OWNER)) == [aug["id"]]
    assert ids(await client.get(f"{EV}?calendar={cals['U']}", headers=OWNER)) == [other["id"]]

    # a series intersects a far range, a one-off only its own
    december = await client.get(
        f"{EV}?from=2026-12-01T00:00:00Z&to=2026-12-31T00:00:00Z", headers=OWNER
    )
    assert ids(december) == [series["id"]]
    first_day = await client.get(
        f"{EV}?from=2026-07-01T00:00:00Z&to=2026-07-02T00:00:00Z", headers=OWNER
    )
    assert set(ids(first_day)) == {july["id"], series["id"], other["id"]}
    assert (
        ids(
            await client.get(
                f"{EV}?from=2026-08-05T10:30:00Z&to=2026-08-06T00:00:00Z", headers=OWNER
            )
        ).count(aug["id"])
        == 1
    )
    assert aug["id"] not in ids(
        await client.get(f"{EV}?from=2026-08-05T11:00:00Z", headers=OWNER)
    )  # ends at 11:00

    # q matches any language's title, case-insensitively
    assert ids(await client.get(f"{EV}?q=konz", headers=OWNER)) == [july["id"]]
    assert ids(await client.get(f"{EV}?q=KONZERT&locale=de", headers=OWNER)) == [july["id"]]
    titled = await client.get(f"{EV}?locale=de", headers=OWNER)
    shown = {i["id"]: (i["title"], i["lang"]) for i in titled.json()["items"]}
    assert shown[july["id"]] == ("Konzert", "de")
    assert shown[series["id"]] == ("Weekly", "en")  # no German text: the default language

    page = await client.get(f"{EV}?page_size=3&page=2", headers=OWNER)
    assert (
        page.json()["total"] == 4
        and len(page.json()["items"]) == 1
        and page.json()["page_size"] == 3
    )
    assert ids(await client.get(f"{EV}?page=9", headers=OWNER)) == []
    for bad in (
        "page_size=101",
        "page_size=0",
        "page=0",
        "status=bogus",
        "q=" + "x" * 101,
        "from=2026-07-01T00:00:00",
    ):
        assert (await client.get(f"{EV}?{bad}", headers=OWNER)).status_code == 422, bad


async def test_q_is_a_literal_substring(client):
    cal = (await cast(client))["I"]
    sale = await create(client, cal, texts={"en": {"title": "100% sale_day"}})
    await create(client, cal, texts={"en": {"title": "1000 saleXday"}})
    assert ids(await client.get(EV, params={"q": "100%"}, headers=OWNER)) == [sale["id"]]
    assert ids(await client.get(EV, params={"q": "sale_day"}, headers=OWNER)) == [sale["id"]]


async def test_scheduled_filter_and_item_rights(client):
    cal = (await cast(client))["I"]
    plain = await create(client, cal)
    sched = await create(client, cal)
    await client.post(
        f"{EV}/{sched['id']}/approve",
        json={"expected_revision": 1, "publish_at_local": "2099-01-01T10:00"},
        headers=OWNER_PUB,
    )
    only = await client.get(f"{EV}?status=scheduled", headers=OWNER)
    assert ids(only) == [sched["id"]]
    item = only.json()["items"][0]
    assert (item["scheduled"], item["locked"], item["can_write"], item["can_publish"]) == (
        True,
        True,
        True,
        False,
    )
    both = {i["id"]: i for i in (await client.get(EV, headers=OWNER_PUB)).json()["items"]}
    assert both[plain["id"]]["can_publish"] is True and both[plain["id"]]["locked"] is False


async def test_trashed_list_only_restorable(client):
    cals = await cast(client)
    cal = cals["I"]
    mine = await create(client, cal)
    live = await seed_event(client, cal, status="published")
    await create(client, cal)  # a live one stays out of the trash list
    for event in (mine, live):
        rev = event["revision"]
        assert (
            await client.delete(f"{EV}/{event['id']}?expected_revision={rev}", headers=OWNER_PUB)
        ).status_code == 204
    assert set(ids(await client.get(f"{EV}?trashed=true", headers=OWNER))) == {
        mine["id"],
        live["id"],
    }
    assert set(ids(await client.get(f"{EV}?trashed=true", headers=MANAGER))) == {
        mine["id"],
        live["id"],
    }
    assert set(ids(await client.get(f"{EV}?trashed=true", headers=STRANGER))) == {
        mine["id"],
        live["id"],
    }  # events.edit on an internal calendar
    assert (
        ids(await client.get(f"{EV}?trashed=true", headers=VIEWER)) == []
    )  # can see it, could not restore it
    assert mine["id"] not in ids(await client.get(EV, headers=OWNER))
    # the events of a trashed calendar are not restorable until the calendar is
    gone = await client.delete(f"{BASE}/calendars/{cal}", headers=OWNER)
    assert gone.status_code == 204
    assert ids(await client.get(f"{EV}?trashed=true", headers=OWNER)) == []
    assert ids(await client.get(f"{EV}?trashed=true", headers=MANAGER)) == []


async def test_draft_and_trash_never_leak_to_viewers_in_the_list(client):
    cal = (await cast(client))["I"]
    await seed_event(client, cal, status="draft")
    live = await seed_event(client, cal, status="published")
    assert ids(await client.get(EV, headers=VIEWER)) == [live["id"]]
    total = (await client.get(EV, headers=VIEWER)).json()["total"]
    assert total == 1  # a count never admits a hidden event either


ROUTES = [
    ("GET", "{id}", None),
    ("PATCH", "{id}", {"expected_revision": 1, "venue_name": "x"}),
    ("DELETE", "{id}?expected_revision=1", None),
    ("POST", "{id}/restore", {"expected_revision": 1}),
    ("POST", "{id}/submit", {"expected_revision": 1}),
    ("POST", "{id}/withdraw", {"expected_revision": 1}),
    ("POST", "{id}/approve", {"expected_revision": 1}),
    ("POST", "{id}/reject", {"expected_revision": 1, "note": "n"}),
    ("POST", "{id}/unschedule", {"expected_revision": 1}),
    ("POST", "{id}/unpublish", {"expected_revision": 1}),
    ("GET", "{id}/revisions", None),
    ("GET", "{id}/revisions/1", None),
    (
        "POST",
        "{id}/overrides",
        {"expected_revision": 1, "original_start": "2026-07-08T08:00:00Z", "kind": "skipped"},
    ),
    ("DELETE", "{id}/overrides/1?expected_revision=1", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_tenant_isolation(multi_client, method, path, body):
    client = multi_client
    from tests.support.app import as_user

    a = as_user("o", "events.view", "events.edit", "events.publish", tenant="a")
    b = as_user("o", "events.view", "events.edit", "events.publish", "events.manage", tenant="b")
    cal = await client.post(f"{BASE}/calendars", json={"name": "A's"}, headers=a)
    assert cal.status_code == 201, cal.text
    made = await client.post(
        EV,
        json={
            "calendar_id": cal.json()["id"],
            "times": {"timezone": "UTC", "start": "2026-07-01T10:00", "end": "2026-07-01T11:00"},
            "texts": {"en": {"title": "A's event"}},
            "rrule": "FREQ=WEEKLY;BYDAY=WE",
        },
        headers=a,
    )
    assert made.status_code == 201, made.text
    event_id = made.json()["id"]
    url = f"{EV}/{path.format(id=event_id)}"
    got = await client.request(method, url, json=body, headers=b)
    assert (got.status_code, got.json()) == (404, {"detail": "Not found", "code": "not_found"}), (
        got.text
    )
    # b can neither list it nor read it through the occurrences, nor use it in a preview
    assert (await client.get(EV, headers=b)).json()["total"] == 0
    window = f"{BASE}/occurrences?start=2026-07-01T00:00:00Z&end=2026-08-01T00:00:00Z"
    assert (await client.get(window, headers=b)).json()["items"] == []
    preview = await client.post(
        f"{BASE}/recurrence/preview",
        json={
            "event_id": event_id,
            "times": {"timezone": "UTC", "start": "2026-07-01T10:00", "end": "2026-07-01T11:00"},
        },
        headers=b,
    )
    assert preview.status_code == 404
    # nor create one in A's calendar
    into = await client.post(
        EV,
        json={
            "calendar_id": cal.json()["id"],
            "times": {"timezone": "UTC", "start": "2026-07-01T10:00", "end": "2026-07-01T11:00"},
            "texts": {"en": {"title": "x"}},
        },
        headers=b,
    )
    assert into.status_code == 404
    assert (await client.get(f"{EV}/{event_id}", headers=a)).status_code == 200
