"""``GET /api/events/events/{id}/registrations``: the seats taken per occurrence, for the editor."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sm_events.calendar.plugins import registry
from sm_events.models import Event, RegistrationCount

from tests.support.events_http import (
    EV,
    OWNER,
    SHARE_EDIT,
    SHARE_VIEW,
    STRANGER,
    VIEWER,
    cast,
    create,
    run,
    seed_event,
)
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID, install_provider, provider

BUILTIN = {"mode": "builtin", "provider": PROVIDER_ID, "target": KNOWN_TARGET, "capacity": 3}


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    install_provider(monkeypatch, provider())
    yield
    registry.reset_registry()


async def counted(client, event_id: str, *pairs: tuple[str, int]) -> None:
    async def go(db):
        for key, taken in pairs:
            db.add(
                RegistrationCount(
                    event_id=uuid.UUID(event_id), occurrence_key=key or event_id, taken=taken
                )
            )

    await run(client, go)


async def test_counts_for_a_one_off(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal, registration=BUILTIN)
    await counted(client, made["id"], ("", 2))
    got = await client.get(f"{EV}/{made['id']}/registrations", headers=OWNER)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["total"] == 1
    (item,) = body["items"]
    assert (item["occurrence_key"], item["taken"], item["capacity"]) == (made["id"], 2, 3)
    assert item["start"].startswith("2026-07-01T08:00:00")
    assert item["start_local"] == "2026-07-01T10:00"
    assert set(item) == {"occurrence_key", "start", "start_local", "taken", "capacity"}


async def test_series_upcoming_first_then_past(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal, rrule="FREQ=WEEKLY;BYDAY=WE", registration=BUILTIN)
    eid = made["id"]
    keys = [f"{eid}:2026071{d}T080000Z" for d in (5,)] + [
        f"{eid}:20260708T080000Z",
        f"{eid}:20260701T080000Z",
    ]
    await counted(client, eid, *((k, n + 1) for n, k in enumerate(keys)))
    got = await client.get(f"{EV}/{eid}/registrations", headers=OWNER)
    items = got.json()["items"]
    # 'now' in these tests is the real clock: every 2026 date is either past or future, and the
    # order is "upcoming ascending, then past, most recent first", whichever side they fall on.
    starts = [i["start"] for i in items]
    now = datetime.now(UTC).isoformat()
    upcoming = [s for s in starts if s > now]
    past = [s for s in starts if s <= now]
    assert starts == upcoming + past
    assert upcoming == sorted(upcoming) and past == sorted(past, reverse=True)
    assert {i["occurrence_key"] for i in items} == set(keys)


async def test_a_skipped_occurrence_still_shows_its_seats_without_a_time(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal, rrule="FREQ=WEEKLY;BYDAY=WE", registration=BUILTIN)
    key = f"{made['id']}:20260708T080000Z"
    await counted(client, made["id"], (key, 1))

    async def skip(db):
        from sm_events.models import OccurrenceOverride

        db.add(
            OccurrenceOverride(
                event_id=uuid.UUID(made["id"]),
                original_start=datetime(2026, 7, 8, 8, tzinfo=UTC),
                kind="skipped",
            )
        )

    await run(client, skip)
    (item,) = (await client.get(f"{EV}/{made['id']}/registrations", headers=OWNER)).json()["items"]
    assert (item["occurrence_key"], item["taken"], item["start"], item["start_local"]) == (
        key,
        1,
        None,
        None,
    )


async def test_empty_and_bounded(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal, registration=BUILTIN)
    got = await client.get(f"{EV}/{made['id']}/registrations", headers=OWNER)
    assert got.json() == {"items": [], "total": 0}


async def test_a_one_off_without_seats_or_registration_is_just_empty(client):
    cal = (await cast(client))["I"]
    made = await create(client, cal)
    assert (await client.get(f"{EV}/{made['id']}/registrations", headers=OWNER)).json()[
        "total"
    ] == 0


async def test_needs_the_write_right(client):
    cals = await cast(client)
    made = await seed_event(client, cals["I"], status="published")
    url = f"{EV}/{made['id']}/registrations"
    assert (await client.get(url)).status_code == 401
    for who in (VIEWER, SHARE_VIEW):
        got = await client.get(url, headers=who)
        assert got.status_code == 404, who  # a viewer sees the event, and the same absence
        assert got.json()["code"] == "not_found"
    private = await seed_event(client, cals["P"], status="published")
    got = await client.get(f"{EV}/{private['id']}/registrations", headers=STRANGER)
    assert got.status_code == 404  # no share on a private calendar
    assert (await client.get(url, headers=SHARE_EDIT)).status_code == 200  # an edit share writes
    assert (await client.get(url, headers=OWNER)).status_code == 200


async def test_a_draft_and_a_missing_event_are_absent(client):
    cal = (await cast(client))["I"]
    draft = await seed_event(client, cal)
    for who in (VIEWER, SHARE_VIEW):
        assert (
            await client.get(f"{EV}/{draft['id']}/registrations", headers=who)
        ).status_code == 404
    assert (
        await client.get(f"{EV}/{uuid.uuid4()}/registrations", headers=OWNER)
    ).status_code == 404


@pytest.mark.unbound_tenant
async def test_another_tenants_event_is_absent(multi_client):
    from tests.support.app import as_user

    async def seed(db):
        from sm_events.models import Calendar

        cal = Calendar(slug="c", name="C", owner_id="o", visibility="public")
        db.add(cal)
        await db.flush()
        ev = Event(
            calendar_id=cal.id,
            starts_at=datetime(2026, 7, 1, 8, tzinfo=UTC),
            ends_at=datetime(2026, 7, 1, 9, tzinfo=UTC),
            timezone="UTC",
            uid="x@simple-module-events",
            status="published",
        )
        db.add(ev)
        await db.flush()
        return str(ev.id)

    from sm_events.core.tenancy import tenant_scope

    with tenant_scope("acme"):
        async with multi_client.db_state.session_factory() as db:
            event_id = await seed(db)
            await db.commit()
    other = as_user("o", "events.view", "events.edit", tenant="globex")
    mine = as_user("o", "events.view", "events.edit", tenant="acme")
    assert (
        await multi_client.get(f"{EV}/{event_id}/registrations", headers=other)
    ).status_code == 404
    assert (
        await multi_client.get(f"{EV}/{event_id}/registrations", headers=mine)
    ).status_code == 200
