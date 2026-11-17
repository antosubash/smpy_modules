"""``GET /api/events/occurrences`` over HTTP: bounds, filters and visibility."""

from __future__ import annotations

import uuid

from tests.support.events_http import (
    EV,
    OWNER,
    OWNER_PUB,
    VIEWER,
    cast,
    create,
    seed_event,
)

OCC = "/api/events/occurrences"
JULY = "start=2026-07-01T00:00:00Z&end=2026-08-01T00:00:00Z"


async def test_occurrences_api_bounds(client):
    for query in (
        "start=2026-07-01T00:00:00&end=2026-07-02T00:00:00Z",  # naive start
        "start=2026-07-01T00:00:00Z&end=2026-07-02T00:00:00",  # naive end
        "start=2026-07-01T00:00:00Z",  # missing end
        "start=nonsense&end=2026-07-02T00:00:00Z",
    ):
        assert (await client.get(f"{OCC}?{query}", headers=OWNER)).status_code == 422, query
    year = await client.get(
        f"{OCC}?start=2026-01-01T00:00:00Z&end=2027-01-03T00:00:00Z", headers=OWNER
    )
    assert (year.status_code, year.json()["code"]) == (422, "range_too_long")
    exact = await client.get(
        f"{OCC}?start=2026-01-01T00:00:00Z&end=2027-01-02T00:00:00Z", headers=OWNER
    )
    assert exact.status_code == 200 and exact.json() == {"items": [], "truncated": False}
    backwards = await client.get(
        f"{OCC}?start=2026-07-02T00:00:00Z&end=2026-07-01T00:00:00Z", headers=OWNER
    )
    assert (backwards.status_code, backwards.json()["code"]) == (422, "invalid_range")
    offset = await client.get(
        f"{OCC}?start=2026-07-01T02:00:00%2B02:00&end=2026-07-02T00:00:00Z", headers=OWNER
    )
    assert offset.status_code == 200  # an offset is a timezone too


async def test_occurrence_shape_and_editor_url(client):
    cal = (await cast(client))["I"]
    event = await create(client, cal, rrule="FREQ=WEEKLY;BYDAY=WE;COUNT=2", venue_name="Hall")
    got = await client.get(f"{OCC}?{JULY}", headers=OWNER)
    items = got.json()["items"]
    assert [i["start"][:13] for i in items] == ["2026-07-01T08", "2026-07-08T08"]
    first = items[0]
    assert first["key"] == event["id"] + ":20260701T080000Z" and first["source"] == "events"
    assert first["title"] == "Concert" and first["lang"] == "en" and first["status"] == "confirmed"
    assert first["editable"] is True and first["url"] == f"/admin/events/edit/{event['id']}"
    assert first["event_status"] == "draft" and first["all_day"] is False
    assert first["calendar_id"] == cal and first["timezone"] == "Europe/Vienna"


async def test_view_only_sees_published_only(client):
    cal = (await cast(client))["I"]
    live = await seed_event(client, cal, status="published")
    await seed_event(client, cal, status="draft")
    await seed_event(client, cal, status="in_review")
    scheduled = await create(client, cal)
    sched = await client.post(
        f"{EV}/{scheduled['id']}/approve",
        json={"expected_revision": 1, "publish_at_local": "2099-01-01T10:00"},
        headers=OWNER_PUB,
    )
    assert sched.status_code == 200 and sched.json()["scheduled"] is True
    got = await client.get(f"{OCC}?{JULY}", headers=VIEWER)
    assert [i["event_id"] for i in got.json()["items"]] == [live["id"]]
    item = got.json()["items"][0]
    assert item["editable"] is False and item["url"] is None
    listed = await client.get(EV, headers=VIEWER)
    assert [e["id"] for e in listed.json()["items"]] == [live["id"]]
    # a writer asking for published only (include_unpublished=false) gets just that too
    only = await client.get(f"{OCC}?{JULY}&include_unpublished=false", headers=OWNER)
    assert [i["event_id"] for i in only.json()["items"]] == [live["id"]]
    both = await client.get(f"{OCC}?{JULY}", headers=OWNER)
    assert len(both.json()["items"]) == 4


async def test_filters_and_invisible_calendars_are_dropped_silently(client):
    cals = await cast(client)
    mine = await seed_event(client, cals["I"], status="published")
    private = await seed_event(client, cals["P"], status="published")
    ids = f"calendar={cals['I']}&calendar={cals['P']}&calendar={uuid.uuid4()}"
    got = await client.get(
        f"{OCC}?{JULY}&{ids}", headers=VIEWER
    )  # P is private: a viewer has no access
    assert [i["event_id"] for i in got.json()["items"]] == [mine["id"]]
    owner = await client.get(f"{OCC}?{JULY}&{ids}", headers=OWNER)
    assert {i["event_id"] for i in owner.json()["items"]} == {mine["id"], private["id"]}
    typed = await client.get(f"{OCC}?{JULY}&type=meeting", headers=OWNER)
    assert typed.json()["items"] == []
    kind = await client.get(f"{OCC}?{JULY}&type=event&type=meeting", headers=OWNER)
    assert len(kind.json()["items"]) == 2
    cat = await client.get(f"{OCC}?{JULY}&category={uuid.uuid4()}", headers=OWNER)
    assert cat.json()["items"] == []


async def test_locale_query_picks_the_title(locales_client):
    client = locales_client
    cal = (await cast(client))["I"]
    await create(client, cal, texts={"en": {"title": "Concert"}, "de": {"title": "Konzert"}})
    de = await client.get(f"{OCC}?{JULY}&locale=de", headers=OWNER)
    assert (de.json()["items"][0]["title"], de.json()["items"][0]["lang"]) == ("Konzert", "de")
    fr = await client.get(f"{OCC}?{JULY}&locale=fr", headers=OWNER)
    assert (fr.json()["items"][0]["title"], fr.json()["items"][0]["lang"]) == ("Concert", "en")


async def test_anonymous_is_refused(client):
    got = await client.get(f"{OCC}?{JULY}")
    assert got.status_code in (401, 403)
