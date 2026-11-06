"""The one conditional Core ``UPDATE`` every campaign status change goes through.

:func:`transition` is pinned to the campaign's id, its tenant and the statuses
it may leave, and bumps ``revision``; :func:`apply_transition` adds the
refusal (:mod:`~sm_newsletter.campaigns._refusal`) when it changes no row, and
the campaign re-read. Neither commits: the caller does, so a refusal leaves
nothing behind.
"""

from __future__ import annotations

from typing import Any

from simple_module_db import mark_written
from simple_module_db.listeners import current_user_id
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns._refusal import refusal
from sm_newsletter.campaigns.access import Roles, require_campaign
from sm_newsletter.core.clock import utcnow
from sm_newsletter.models import Campaign

__all__ = ["apply_transition", "transition"]


async def transition(
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    from_statuses: tuple[str, ...],
    values: dict[str, Any],
    expected_revision: int | None = None,
    where: list[Any] | None = None,
) -> bool:
    """Write ``values`` onto the campaign if its status is one of
    ``from_statuses`` (and its revision ``expected_revision``, and ``where``),
    bumping the revision. Whether a row changed; never commits."""
    where = [
        Campaign.id == campaign_id,
        Campaign.tenant_id == tenant_id,
        Campaign.status.in_(from_statuses),
        *(where or []),
    ]
    if expected_revision is not None:
        where.append(Campaign.revision == expected_revision)
    # A Core-style UPDATE skips the audit listener: stamp what it would.
    stamped = {"updated_at": utcnow(), "updated_by": current_user_id.get(), **values}
    stmt = (
        update(Campaign)
        .where(*where)
        .values(**stamped, revision=Campaign.revision + 1)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    mark_written(session)
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


async def apply_transition(
    session: AsyncSession,
    tenant_id: str,
    campaign_id: int,
    roles: Roles,
    from_statuses: tuple[str, ...],
    values: dict[str, Any],
    *,
    revision: int | None = None,
    stale_on_revision: bool = True,
    where: list[Any] | None = None,
) -> Campaign:
    """:func:`transition`, its refusal when nothing changed, and the campaign re-read."""
    key = {"tenant_id": tenant_id, "campaign_id": campaign_id}
    if not await transition(
        session,
        **key,
        from_statuses=from_statuses,
        values=values,
        expected_revision=revision,
        where=where,
    ):
        pinned = stale_on_revision and revision is not None
        raise await refusal(session, **key, from_statuses=from_statuses, pinned_revision=pinned)
    return await require_campaign(session, **key, roles=roles)
