"""A freeze's pages: the audience, read from records a page at a time, into send rows.

Every page renews the claim (:func:`~.freeze_fence.hold_freeze`) inside its own
transaction before writing, so its rows commit only while the claim holds. The
lock order is the never-started campaign's: the campaign row first (the
renewal), then the send rows.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sm_records.contracts.newsletter import (
    MAX_SUBSCRIBER_BATCH,
    SubscriberHit,
    iter_subscribers,
)

from sm_newsletter.core.constants import MAX_EMAIL_LEN, MAX_FIRST_NAME_LEN
from sm_newsletter.core.suppression import normalise_email, suppressed
from sm_newsletter.core.upsert import insert_ignore
from sm_newsletter.models import Send
from sm_newsletter.sending.freeze_fence import FreezeClaim, SessionFactory, hold_freeze

__all__ = ["PAGE", "QUEUED", "SUPPRESSED", "write_pages"]

PAGE = MAX_SUBSCRIBER_BATCH
QUEUED, SUPPRESSED = "queued", "suppressed"

_SEND = Send.__table__  # ty: ignore[unresolved-attribute]

Reader = Callable[..., Awaitable[tuple[list[SubscriberHit], int | None]]]


async def write_pages(
    factory: SessionFactory,
    tenant_id: str,
    campaign_id: int,
    claim: FreezeClaim,
    list_key: str,
    filters: Sequence[str],
    clock: Callable[[], datetime],
    *,
    read: Reader = iter_subscribers,
    page: int = PAGE,
) -> bool:
    """Every page of the audience into send rows; ``False`` once the claim is lost.

    ``read`` and ``page`` default to records' reader and its largest batch;
    :mod:`.freeze` passes its own names so a test can swap them there."""
    cursor: int | None = 0
    while cursor is not None:
        async with factory() as session:
            hits, cursor = await read(
                session,
                tenant_id=tenant_id,
                type_key=list_key,
                filters=list(filters),
                limit=page,
                after=cursor,
            )
            # Records caps neither length; the send columns do. A blank or
            # over-long address could not be delivered and is left out; a long
            # name is clipped (Postgres would refuse the whole page).
            hits = [hit for hit in hits if 0 < len(hit.email.strip()) <= MAX_EMAIL_LEN]
            emails = [hit.email for hit in hits]
            blocked = await suppressed(session, tenant_id=tenant_id, emails=emails)
            if not await hold_freeze(
                session, claim, tenant_id=tenant_id, campaign_id=campaign_id, now=clock()
            ):
                await session.rollback()
                return False
            rows: list[dict[str, Any]] = [
                {
                    "tenant_id": tenant_id,
                    "campaign_id": campaign_id,
                    "record_uuid": hit.uuid,
                    "email": hit.email.strip(),
                    "first_name": (hit.first_name or "")[:MAX_FIRST_NAME_LEN] or None,
                    "status": SUPPRESSED if normalise_email(hit.email) in blocked else QUEUED,
                    "freeze_gen": claim.gen,
                }
                for hit in hits
            ]
            if rows:
                await insert_ignore(
                    session, _SEND, rows, conflict=["tenant_id", "campaign_id", "record_uuid"]
                )
            await finalize_session(session)
    return True
