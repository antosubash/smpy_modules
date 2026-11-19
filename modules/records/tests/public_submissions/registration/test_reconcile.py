"""Seat reconciliation: it frees what no live registration holds, pages, and never admits."""

from __future__ import annotations

import uuid

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import RegistrationCount, RegistrationSeat
from sm_records.core.tenancy import tenant_scope as records_scope
from sm_records.public_submissions.registration import mail as reg_mail
from sm_records.public_submissions.registration import reconcile

from tests.support.app_harness import ADMIN, roles
from tests.support.registration_http import (
    TYPE,
    record_url,
    register,
    regs,
    seat_counts,
    seed_event,
)

pytestmark = pytest.mark.usefixtures("reg_site")


@pytest.fixture(autouse=True)
def _quiet_mail(monkeypatch):
    async def quiet(*_a, **_k):
        return None

    monkeypatch.setattr(reg_mail, "queue_registration_mail", quiet)


async def leak(site, holder: str) -> None:
    """A seat with no (live) registration behind it, as a path outside the hooks would leave."""
    from sqlalchemy import func, select, update

    with tenant_scope("default"):
        async with site.db_state.session_factory() as db:
            ev = uuid.UUID(site.event["event_id"])
            db.add(
                RegistrationSeat(
                    event_id=ev,
                    occurrence_key=site.event["key"],
                    provider="records:registration",
                    target=TYPE,
                    holder=holder,
                )
            )
            await db.flush()
            held = (
                await db.execute(
                    select(func.count())
                    .select_from(RegistrationSeat)
                    .where(RegistrationSeat.event_id == ev)
                )
            ).scalar_one()
            await db.execute(
                update(RegistrationCount.__table__)  # type: ignore[attr-defined]
                .where(RegistrationCount.__table__.c.event_id == ev)  # type: ignore[attr-defined]
                .values(taken=held)
            )
            await db.commit()


async def run(site, **kw) -> int:
    with records_scope("default"):
        return await reconcile.reconcile(site.db_state.session_factory, **kw)


async def test_reconcile_frees_leaked(reg_site):
    await register(reg_site, "live@example.org")
    await register(reg_site, "gone@example.org")
    items = {r["data"]["sm_email"]: r for r in await regs(reg_site)}
    cancel = await reg_site.post(
        record_url(items["gone@example.org"]["uuid"], "/submission/cancel"), headers=roles(ADMIN)
    )
    assert cancel.status_code == 200
    # a cancelled registration whose seat came back (a path outside the hooks), plus one nobody has
    await leak(reg_site, str(uuid.UUID(items["gone@example.org"]["uuid"])))
    await leak(reg_site, str(uuid.uuid4()))
    assert await seat_counts(reg_site) == (3, 3)
    assert await run(reg_site) == 2
    assert await seat_counts(reg_site) == (1, 1)
    assert [
        r["data"]["sm_email"] for r in await regs(reg_site) if r["data"]["sm_status"] == "pending"
    ] == ["live@example.org"]
    assert await run(reg_site) == 0  # idempotent


async def test_it_pages(reg_site):
    for _ in range(5):
        await leak(reg_site, str(uuid.uuid4()))
    await register(reg_site, "live@example.org")
    pages: list[int] = []
    real = reconcile.page_released
    reconcile.page_released = lambda n: pages.append(n)  # type: ignore[assignment]
    try:
        assert await run(reg_site, page=2) == 5
    finally:
        reconcile.page_released = real  # type: ignore[assignment]
    assert len(pages) == 3 and sum(pages) == 5  # six seats, limit 2: three pages
    assert await seat_counts(reg_site) == (1, 1)


async def test_a_trashed_registration_leaking_a_seat_is_freed(reg_site):
    await register(reg_site, "a@example.org")
    (record,) = await regs(reg_site)
    await reg_site.delete(record_url(record["uuid"]), headers=roles(ADMIN))
    await leak(reg_site, str(uuid.UUID(record["uuid"])))
    assert await run(reg_site) == 1 and await seat_counts(reg_site) == (0, 0)


async def test_it_never_admits(reg_site):
    event = await seed_event(reg_site.db_state, uid="n@x", registration_capacity=5)
    await register(reg_site, "a@example.org", event=event)
    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            from sqlalchemy import delete

            await db.execute(delete(RegistrationSeat.__table__))  # type: ignore[attr-defined]
            await db.execute(delete(RegistrationCount.__table__))  # type: ignore[attr-defined]
            await db.commit()
    assert await run(reg_site) == 0
    assert await seat_counts(reg_site) == (0, 0)  # the record is left alone, seatless
    assert len(await regs(reg_site)) == 1


async def test_it_leaves_other_providers_seats_alone(reg_site):
    await leak(reg_site, str(uuid.uuid4()))
    with tenant_scope("default"):
        async with reg_site.db_state.session_factory() as db:
            from sqlalchemy import update

            await db.execute(update(RegistrationSeat.__table__).values(provider="other:provider"))  # type: ignore[attr-defined]
            await db.commit()
    assert await run(reg_site) == 0
