"""Every error code the events API adds, over HTTP: status, code and the exact
``{"detail", "code"}`` body."""

from __future__ import annotations

import uuid

from tests.support.events_http import (
    EV,
    OWNER,
    OWNER_PUB,
    cast,
    create,
    create_json,
    seed_event,
)

WEEKLY = "FREQ=WEEKLY;BYDAY=WE"
OCC = "/api/events/occurrences"
SECOND = "2026-07-08T08:00:00Z"
NOT_ONE = "2026-07-09T08:00:00Z"


def check(got, status: int, code: str, field: str | None = None) -> None:
    """``field`` is the input a refusal names; without one the body has no such key."""
    assert (got.status_code, got.json().get("code")) == (status, code), got.text
    assert set(got.json()) == {"detail", "code"} | ({"field"} if field else set())
    assert got.json()["detail"] and got.json().get("field") == field


async def test_error_envelope_on_every_new_code(locales_client):
    client = locales_client
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    series = await create(client, cal, rrule=WEEKLY)
    published = await seed_event(client, cal, status="published")
    eid, sid = event["id"], series["id"]

    def body(**kw):
        return create_json(cal, **kw)

    async def post(**kw):
        return await client.post(EV, json=body(**kw), headers=OWNER)

    # 409
    check(
        await client.patch(f"{EV}/{eid}", json={"expected_revision": 9}, headers=OWNER),
        409,
        "stale",
    )
    check(
        await client.post(f"{EV}/{eid}/withdraw", json={"expected_revision": 1}, headers=OWNER),
        409,
        "invalid_transition",
    )
    child = await post(parent_id=eid)
    assert child.status_code == 201
    check(
        await client.delete(f"{EV}/{eid}?expected_revision=1", headers=OWNER), 409, "has_sub_events"
    )
    skip = await client.post(
        f"{EV}/{sid}/overrides",
        json={"expected_revision": 1, "original_start": SECOND, "kind": "skipped"},
        headers=OWNER,
    )
    assert skip.status_code == 200
    check(
        await client.patch(
            f"{EV}/{sid}",
            json={"expected_revision": 2, "rrule": "FREQ=WEEKLY;BYDAY=TU",
                  "times": {"timezone": "Europe/Vienna", "start": "2026-06-30T10:00",
                            "end": "2026-06-30T11:00"}},
            headers=OWNER,
        ),
        409, "overrides_orphaned",
    )  # fmt: skip
    check(
        await post(texts={"en": {"title": "x", "slug": "concert"}}),
        409,
        "slug_taken",
        "texts.en.slug",
    )
    # 403
    check(
        await client.patch(
            f"{EV}/{published['id']}",
            json={"expected_revision": 1, "venue_name": "x"},
            headers=OWNER,
        ),
        403, "publish_required",
    )  # fmt: skip
    # 404
    check(await client.get(f"{EV}/{uuid.uuid4()}", headers=OWNER), 404, "not_found")
    # 422
    check(await post(rrule="FREQ=WEEKLY;BYHOUR=3"), 422, "invalid_rrule")
    check(await post(rrule="FREQ=HOURLY"), 422, "rrule_frequency_refused")
    check(await post(rrule="FREQ=WEEKLY;BYDAY=TH"), 422, "start_not_in_rule")
    gap = {"timezone": "Europe/Vienna", "start": "2026-03-29T02:30", "end": "2026-03-29T04:00"}
    check(await post(times=gap), 422, "invalid_local_time", "times.start")
    back = {"timezone": "Europe/Vienna", "start": "2026-07-01T10:00", "end": "2026-07-01T09:00"}
    check(await post(times=back), 422, "end_before_start", "times.end")
    long_ = {"timezone": "Europe/Vienna", "start": "2026-07-01T10:00", "end": "2028-07-01T09:00"}
    check(await post(times=long_), 422, "duration_too_long", "times.end")
    check(
        await client.get(
            f"{OCC}?start=2026-07-01T00:00:00Z&end=2026-07-01T00:00:00Z", headers=OWNER
        ),
        422,
        "invalid_range",
    )
    check(
        await client.get(
            f"{OCC}?start=2026-01-01T00:00:00Z&end=2028-01-01T00:00:00Z", headers=OWNER
        ),
        422,
        "range_too_long",
    )
    check(await post(texts={"de": {"title": "nur deutsch"}}), 422, "default_locale_required")
    check(await post(texts={"en": {"title": "x"}, "fr": {"title": "y"}}), 422, "unknown_locale")
    check(await post(category_id=str(uuid.uuid4())), 422, "unknown_category")
    check(await post(type="meeting"), 422, "unknown_type")
    check(await post(parent_id=str(uuid.uuid4())), 422, "invalid_parent")
    check(
        await client.patch(
            f"{EV}/{eid}", json={"expected_revision": 1, "calendar_id": cal}, headers=OWNER
        ),
        422,
        "immutable_field",
    )
    check(
        await client.post(
            f"{EV}/{eid}/overrides",
            json={"expected_revision": 1, "original_start": SECOND, "kind": "skipped"},
            headers=OWNER,
        ),
        422, "not_recurring",
    )  # fmt: skip
    check(
        await client.post(
            f"{EV}/{sid}/overrides",
            json={"expected_revision": 2, "original_start": NOT_ONE, "kind": "skipped"},
            headers=OWNER,
        ),
        422, "not_an_occurrence",
    )  # fmt: skip
    check(
        await post(texts={"en": {"title": "x", "description": "x" * 200_001}}),
        422, "description_too_long", "texts.en.description",
    )  # fmt: skip


async def test_published_workflow_needs_publish_code(client):
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    check(
        await client.post(
            f"{EV}/{event['id']}/approve", json={"expected_revision": 1}, headers=OWNER
        ),
        403, "publish_required",
    )  # fmt: skip
    ok = await client.post(
        f"{EV}/{event['id']}/approve", json={"expected_revision": 1}, headers=OWNER_PUB
    )
    assert ok.status_code == 200 and ok.json()["status"] == "published"
