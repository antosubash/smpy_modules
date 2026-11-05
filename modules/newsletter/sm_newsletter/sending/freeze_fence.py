"""The freeze fence (amendments A1, A2): one owner per campaign, for one generation.

:func:`claim_freeze` takes the freeze with a conditional ``UPDATE``
(``freeze_owner``/``freeze_until``, on the ``freeze_gen`` it read, only when
nobody holds a live claim); :func:`hold_freeze` renews it, and every write a
freezer makes is conditional on it (:func:`held`). ``schedule``,
``unschedule`` and a cancel from ``scheduled`` bump the generation and release
the claim (``campaigns.lifecycle``), so an old freezer matches nothing.

Also the due-campaign enumeration, the one cross-tenant read of freezing.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from simple_module_db import finalize_session, mark_written
from simple_module_db.tenancy import all_tenants
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.lifecycle import PAUSED, SCHEDULED, paused_reason
from sm_newsletter.core import constants, tenancy
from sm_newsletter.models import Campaign

__all__ = [
    "FREEZE_LEASE",
    "FreezeClaim",
    "SessionFactory",
    "claim_freeze",
    "due_campaigns",
    "held",
    "hold_freeze",
    "pause_unavailable",
    "update_campaign",
]

FREEZE_LEASE = timedelta(minutes=5)

SessionFactory = Callable[[], AsyncSession]
_CAMPAIGN = Campaign.__table__  # ty: ignore[unresolved-attribute]


@dataclass(frozen=True)
class FreezeClaim:
    owner: str
    gen: int


def held(tenant_id: str, campaign_id: int, claim: FreezeClaim) -> list[Any]:
    """The campaign is still scheduled, and this claim still owns its freeze."""
    return [
        Campaign.id == campaign_id,
        Campaign.tenant_id == tenant_id,
        Campaign.status == SCHEDULED,
        Campaign.freeze_owner == claim.owner,
        Campaign.freeze_gen == claim.gen,
    ]


async def update_campaign(session: AsyncSession, where: list[Any], values: dict[str, Any]) -> bool:
    """One conditional Core ``UPDATE`` of the campaign; whether it matched. Never commits."""
    stmt = (
        update(Campaign).where(*where).values(**values).execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    mark_written(session)
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


async def claim_freeze(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, now: datetime
) -> FreezeClaim | None:
    """Take the freeze of a scheduled campaign nobody holds (or whose holder's
    lease ran out); ``None`` otherwise. Leaves ``revision`` alone; never commits."""
    key = [
        Campaign.id == campaign_id,
        Campaign.tenant_id == tenant_id,
        Campaign.status == SCHEDULED,
    ]
    gen = (await session.execute(select(Campaign.freeze_gen).where(*key))).scalar_one_or_none()
    if gen is None:
        return None
    claim = FreezeClaim(owner=f"freeze:{secrets.token_hex(8)}", gen=gen)
    free = or_(Campaign.freeze_owner.is_(None), Campaign.freeze_until < now)
    values = {"freeze_owner": claim.owner, "freeze_until": now + FREEZE_LEASE}
    taken = await update_campaign(session, [*key, Campaign.freeze_gen == gen, free], values)
    return claim if taken else None


async def hold_freeze(
    session: AsyncSession, claim: FreezeClaim, *, tenant_id: str, campaign_id: int, now: datetime
) -> bool:
    """Renew ``claim``'s lease; whether it still holds. Never commits."""
    where = held(tenant_id, campaign_id, claim)
    return await update_campaign(session, where, {"freeze_until": now + FREEZE_LEASE})


async def due_campaigns(factory: SessionFactory, *, now: datetime) -> list[tuple[str, int]]:
    """Every tenant's scheduled campaigns due by ``now``, oldest first, as
    ``(tenant_id, id)``: a deliberate cross-tenant read of pairs only."""
    stmt = (
        select(_CAMPAIGN.c.tenant_id, _CAMPAIGN.c.id)
        .where(_CAMPAIGN.c.status == SCHEDULED, _CAMPAIGN.c.scheduled_at <= now)
        .order_by(_CAMPAIGN.c.scheduled_at, _CAMPAIGN.c.id)
    )
    with all_tenants():
        async with factory() as session:
            rows = (await session.execute(tenancy.all_tenants(stmt))).all()
            await finalize_session(session)
    return [(str(tenant), int(cid)) for tenant, cid in rows]


async def pause_unavailable(
    session: AsyncSession, tenant_id: str, campaign_id: int, claim: FreezeClaim, now: datetime
) -> None:
    """``scheduled -> paused`` (``list_unavailable``) if the claim holds,
    releasing it: ``resume`` sends a never-started campaign back to
    ``scheduled`` without a new generation, so the next tick can claim it."""
    values = {
        "status": PAUSED,
        "paused_reason": paused_reason(constants.PAUSE_LIST_UNAVAILABLE),
        "freeze_owner": None,
        "freeze_until": None,
        "revision": Campaign.revision + 1,
        "updated_at": now,
    }
    await update_campaign(session, held(tenant_id, campaign_id, claim), values)
