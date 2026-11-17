"""Scheduled publishing: what the ``events.publish_due`` beat does.

A platform pass (no tenant bound by the caller). One narrow, tagged read lists the
tenants that have a due event; then each tenant is worked in a session of its own
under its own tenant scope, so nothing crosses tenants and one tenant's failure
is logged, counted and rolled back without stopping the others.

*Due* is a draft or in-review event with ``publish_at <= now`` that is not in the
trash. Each is published by :func:`~sm_events.content.workflow.publish_scheduled`,
whose first statement is the revision compare-and-set: that is also the claim. Two
workers (or a redelivered message) that read the same row cannot both publish it:
the second loses the compare-and-set, skips the row and writes nothing. On Postgres
``FOR UPDATE SKIP LOCKED`` makes the second worker pass over rows the first holds.
At most ``PUBLISH_DUE_BATCH`` rows per tenant per pass; the rest wait for the next.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from simple_module_db import finalize_session
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.content.workflow import publish_scheduled
from sm_events.core import constants
from sm_events.core.errors import NotFound, Stale
from sm_events.core.tenancy import all_tenants, tenant_scope
from sm_events.models import Event
from sm_events.models.enums import EventStatus

__all__ = ["publish_due_async"]

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]
_UNPUBLISHED = (EventStatus.DRAFT.value, EventStatus.IN_REVIEW.value)


def _due(now: datetime) -> tuple:
    return (
        Event.status.in_(_UNPUBLISHED),  # type: ignore[attr-defined]
        Event.publish_at <= now,  # type: ignore[operator]
        Event.is_deleted.is_(False),  # type: ignore[attr-defined]
    )


async def _tenants_with_due(session_factory: SessionFactory, now: datetime) -> list[str]:
    stmt = all_tenants(select(distinct(Event.tenant_id)).where(*_due(now)))
    async with session_factory() as session:
        return sorted((await session.execute(stmt)).scalars())


async def _publish_tenant(session_factory: SessionFactory, now: datetime) -> int:
    """One tenant's due events, in a session of its own; how many were published."""
    published = 0
    async with session_factory() as session:
        stmt = (
            select(Event)
            .where(*_due(now))
            .order_by(Event.publish_at, Event.id)  # type: ignore[arg-type]
            .limit(constants.PUBLISH_DUE_BATCH)
            .with_for_update(skip_locked=True)
        )
        for event in (await session.execute(stmt)).scalars().all():
            try:
                await publish_scheduled(session, event, now=now)
            except (Stale, NotFound):
                continue  # edited, published or trashed meanwhile: the next tick sees it
            published += 1
        await finalize_session(session)
    return published


async def publish_due_async(session_factory: SessionFactory, *, now: datetime) -> dict[str, int]:
    """One pass; ``{"tenants", "published", "failed"}``. ``tenants`` counts those
    with something due."""
    tenants = await _tenants_with_due(session_factory, now)
    published = failed = 0
    for tenant in tenants:
        try:
            with tenant_scope(tenant):
                published += await _publish_tenant(session_factory, now)
        except Exception:
            logger.warning(
                "events: could not publish the due events of tenant %s; the next pass tries again",
                tenant,
                exc_info=True,
            )
            failed += 1
    return {"tenants": len(tenants), "published": published, "failed": failed}
