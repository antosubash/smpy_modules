"""Shared helpers of the seat tests: take, free and read seats through the contract functions."""

from __future__ import annotations

from sm_events.models import RegistrationSeat
from sm_events.registration.seats import admit, release
from sqlalchemy import select

from tests.registration.support import NOW
from tests.support.providers import KNOWN_TARGET, PROVIDER_ID

PROVIDER = PROVIDER_ID


async def take(db, event, holder, key=None, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("provider", PROVIDER)
    kw.setdefault("target", KNOWN_TARGET)
    return await admit(
        db,
        tenant_id="default",
        event_id=event.id,
        occurrence_key=key or str(event.id),
        holder=holder,
        **kw,
    )


async def free(db, *holders, provider=PROVIDER):
    return await release(db, tenant_id="default", provider=provider, holders=list(holders))


async def rows(db):
    return (
        (await db.execute(select(RegistrationSeat).order_by(RegistrationSeat.holder)))
        .scalars()
        .all()
    )
