"""Seats follow every trash, purge and restore path of a registration record (PR 9)."""

from __future__ import annotations

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import RegistrationSeat
from sm_records.public_submissions.registration import mail as reg_mail
from sqlalchemy import update

from tests.support.app_harness import ADMIN, field, roles
from tests.support.public_submissions_support import update as update_type
from tests.support.registration_http import (
    TYPE,
    record_url,
    reg_config,
    reg_fields,
    register_confirmed,
    regs,
    seat_counts,
    seed_event,
)
from tests.support.submissions_http import contact_type

pytestmark = pytest.mark.usefixtures("reg_site")
A = {"headers": roles(ADMIN)}


@pytest.fixture(autouse=True)
def _quiet_mail(monkeypatch):
    async def quiet(*_a, **_k):
        return None

    monkeypatch.setattr(reg_mail, "queue_registration_mail", quiet)


async def two_registered(site):
    assert (await register_confirmed(site, "a@example.org")).status_code == 202
    assert (await register_confirmed(site, "b@example.org")).status_code == 202
    items = await regs(site)
    assert await seat_counts(site) == (2, 2)
    return sorted(items, key=lambda r: r["data"]["sm_email"])


async def trash_one(site, uuid):
    return await site.delete(record_url(uuid), **A)


@pytest.mark.parametrize(
    "path",
    [
        "trash",
        "bulk_trash",
        "empty_trash_after_trash",
        "hard_delete",
        "delete_type",
        "admin_cancel",
    ],
)
async def test_every_path_releases(reg_site, path):
    first, second = await two_registered(reg_site)
    one, two = first["uuid"], second["uuid"]
    if path == "trash":
        assert (await trash_one(reg_site, one)).status_code == 204
        assert await seat_counts(reg_site) == (1, 1)
    elif path == "bulk_trash":
        got = await reg_site.post(
            f"/api/records/types/{TYPE}/records/bulk",
            json={"action": "trash", "uuids": [one, two]},
            **A,
        )
        assert got.status_code == 200, got.text
        assert await seat_counts(reg_site) == (0, 0)
    elif path == "empty_trash_after_trash":
        await trash_one(reg_site, one)
        await trash_one(reg_site, two)
        assert await seat_counts(reg_site) == (0, 0)
        got = await reg_site.post(f"/api/records/types/{TYPE}/records/trash/empty", **A)
        assert got.status_code == 200, got.text
        assert await seat_counts(reg_site) == (0, 0)
    elif path == "hard_delete":
        await trash_one(reg_site, one)
        # a seat that leaked (a record trashed before seats followed it): the purge frees it too
        await leak_seat(reg_site, one)
        assert await seat_counts(reg_site) == (2, 2)
        assert (await reg_site.delete(record_url(one, "/purge"), **A)).status_code == 204
        assert await seat_counts(reg_site) == (1, 1)
    elif path == "delete_type":
        got = await reg_site.delete(f"/api/records/types/{TYPE}?confirm_record_count=2", **A)
        assert got.status_code == 204, got.text
        assert await seat_counts(reg_site) == (0, 0)
    elif path == "admin_cancel":
        got = await reg_site.post(record_url(one, "/submission/cancel"), **A)
        assert got.status_code == 200
        assert await seat_counts(reg_site) == (1, 1)


async def leak_seat(site, uuid):
    import uuid as _uuid

    from sm_events.models import RegistrationCount

    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            ev = _uuid.UUID(site.event["event_id"])
            db.add(
                RegistrationSeat(
                    event_id=ev,
                    occurrence_key=site.event["key"],
                    provider="records:registration",
                    target=TYPE,
                    holder=str(_uuid.UUID(uuid)),
                )
            )
            await db.flush()
            await db.execute(
                update(RegistrationCount.__table__)  # type: ignore[attr-defined]
                .where(RegistrationCount.__table__.c.event_id == ev)  # type: ignore[attr-defined]
                .values(taken=2)
            )
            await db.commit()


async def test_cascade_trash_releases(reg_site):
    from tests.support.public_submissions_support import create

    await create(reg_site, "people", fields=[field("name", indexed=False)], config=None)
    return_type = await update_type(
        reg_site,
        TYPE,
        fields=[*reg_fields_with_person()],
        public_submissions=reg_config(),
    )
    assert return_type.status_code == 200, return_type.text
    person = await reg_site.post(
        "/api/records/types/people/records", json={"data": {"name": "Pat"}}, **A
    )
    assert person.status_code == 201, person.text
    await register_confirmed(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    link = await reg_site.put(
        record_url(record["uuid"]),
        json={
            "data": {"person": {"type": "people", "uuid": person.json()["uuid"]}},
            "expected_version": record["version"],
        },
        **A,
    )
    assert link.status_code == 200, link.text
    assert await seat_counts(reg_site) == (1, 1)
    gone = await reg_site.delete("/api/records/types/people/records/" + person.json()["uuid"], **A)
    assert gone.status_code == 204, gone.text
    assert await seat_counts(reg_site) == (0, 0)
    assert len(await regs(reg_site, trashed=True)) == 1


def reg_fields_with_person():
    person = field("person", "relation", indexed=False, target_type="people", on_delete="cascade")
    return [*reg_fields(), person]


async def test_mark_as_spam_is_not_a_registration_action(reg_site):
    await register_confirmed(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    got = await reg_site.post(record_url(record["uuid"], "/submission/spam"), **A)
    assert (got.status_code, got.json()["code"]) == (409, "wrong_kind")
    assert await seat_counts(reg_site) == (1, 1)


async def test_restore_readmits(reg_site):
    await register_confirmed(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    await trash_one(reg_site, record["uuid"])
    assert await seat_counts(reg_site) == (0, 0)
    got = await reg_site.post(record_url(record["uuid"], "/restore"), **A)
    assert got.status_code == 200, got.text
    assert await seat_counts(reg_site) == (1, 1)
    again = await reg_site.post(record_url(record["uuid"], "/restore"), **A)
    assert again.status_code == 409  # not in the trash any more: nothing re-admitted twice
    assert await seat_counts(reg_site) == (1, 1)


async def test_restore_refused_when_full(reg_site):
    event = await seed_event(reg_site.db_state, uid="cap@x", registration_capacity=1)
    tokens = [await _token(reg_site, event) for _ in range(2)]
    await register_confirmed(reg_site, "a@example.org", event=event, token=tokens[0])
    (first,) = await regs(reg_site)
    await trash_one(reg_site, first["uuid"])
    await register_confirmed(reg_site, "b@example.org", event=event, token=tokens[1])
    assert await seat_counts(reg_site) == (1, 1)
    got = await reg_site.post(record_url(first["uuid"], "/restore"), **A)
    assert (got.status_code, got.json()["code"]) == (409, "registration_full")
    assert [r["uuid"] for r in await regs(reg_site, trashed=True)] == [first["uuid"]]
    assert await seat_counts(reg_site) == (1, 1)


async def _token(site, event):
    from tests.support.registration_http import load_registration

    return (await load_registration(site, event)).json()["definition"]["token"]


async def test_restore_refused_when_the_event_is_gone(reg_site):
    from sm_events.models import Event

    await register_confirmed(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    await trash_one(reg_site, record["uuid"])
    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            await db.execute(update(Event.__table__).values(status="draft"))  # type: ignore[attr-defined]
            await db.commit()
    got = await reg_site.post(record_url(record["uuid"], "/restore"), **A)
    assert (got.status_code, got.json()["code"]) == (409, "event_unavailable")
    assert await seat_counts(reg_site) == (0, 0)


async def test_a_cancelled_registration_restores_without_a_seat(reg_site):
    await register_confirmed(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    await reg_site.post(record_url(record["uuid"], "/submission/cancel"), **A)
    await trash_one(reg_site, record["uuid"])
    got = await reg_site.post(record_url(record["uuid"], "/restore"), **A)
    assert got.status_code == 200 and await seat_counts(reg_site) == (0, 0)


async def test_non_registration_untouched(reg_site):
    from sqlalchemy import event as sa_event

    await contact_type(reg_site)
    from tests.support.submissions_http import send

    assert (await send(reg_site)).status_code == 202
    (record,) = (await reg_site.get("/api/records/types/contact/records", **A)).json()["items"]
    seen: list[str] = []

    def spy(_conn, _cursor, statement, *_rest):
        seen.append(statement)

    engine = reg_site.db_state.engine.sync_engine
    sa_event.listen(engine, "before_cursor_execute", spy)
    try:
        await reg_site.delete(record_url(record["uuid"], key="contact"), **A)
        await reg_site.post(record_url(record["uuid"], "/restore", key="contact"), **A)
        await reg_site.delete(record_url(record["uuid"], key="contact"), **A)
        await reg_site.delete(record_url(record["uuid"], "/purge", key="contact"), **A)
    finally:
        sa_event.remove(engine, "before_cursor_execute", spy)
    assert not [s for s in seen if "events_registration" in s]


async def test_a_busy_release_is_try_again_everywhere(reg_site, monkeypatch):
    """``SeatsBusy`` from events is a 409 on every records path that releases, never a 500, and
    nothing is half-done (the record keeps its state)."""
    from sm_events.contracts import registration as contract
    from sm_events.core.errors_registration import SeatsBusy

    await register_confirmed(reg_site, "a@example.org")
    (record,) = await regs(reg_site)

    async def busy(*_a, **_k):
        raise SeatsBusy

    monkeypatch.setattr(contract, "release", busy)
    monkeypatch.setattr(contract, "release_target", busy)
    for call in (
        reg_site.post(record_url(record["uuid"], "/submission/cancel"), **A),
        reg_site.delete(record_url(record["uuid"]), **A),
        reg_site.delete(f"/api/records/types/{TYPE}?confirm_record_count=1", **A),
    ):
        got = await call
        assert got.status_code == 409, got.text
    (still,) = await regs(reg_site)
    assert still["data"]["sm_status"] == "registered" and await seat_counts(reg_site) == (1, 1)
