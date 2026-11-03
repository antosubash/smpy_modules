"""The hourly reconcile: every list's opt-outs, re-read from records into the store.

The event mirror (:mod:`sm_newsletter.core.suppression.mirror`) is the fast
path; this is the one that makes a lost or failed event cost latency, not
correctness. Records is the truth, so the walk asks it:

1. :func:`subscription_list_tenants` - which tenants own a list - in one short
   session with no tenant bound (records' one cross-tenant read; it refuses a
   bound tenant);
2. per tenant, under :func:`~sm_newsletter.core.tenancy.tenant_scope`,
   :func:`subscription_lists`;
3. per list, one fresh session per page: ``iter_subscribers(status=
   "unsubscribed", include_trashed=True)`` - a trashed opt-out is still an
   opt-out - into :func:`suppress_many` with ``refresh=False`` (pure
   insert-ignore: the count is what was *new*, a second run says 0, and an
   existing row never looks newer than it is), finished with
   ``finalize_session``.

It only ever adds rows; clearing is a confirmation's job. A list that raises
(``SubscriberFilterError`` - the type stopped being a list mid-walk - or
anything else) is logged and counted in ``"failed"``, and so is a tenant whose
lists cannot be read; the walk goes on. Only a failure to enumerate the tenants
propagates: then nothing ran, and the task should say so.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from simple_module_db import finalize_session, no_tenant
from sm_records.contracts.newsletter import (
    MAX_SUBSCRIBER_BATCH,
    iter_subscribers,
    subscription_list_tenants,
    subscription_lists,
)
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.constants import REASON_UNSUBSCRIBED
from sm_newsletter.core.suppression.store import suppress_many
from sm_newsletter.core.tenancy import tenant_scope

__all__ = ["PAGE_SIZE", "SOURCE", "reconcile_async"]

logger = logging.getLogger(__name__)

SOURCE = "reconcile"
PAGE_SIZE = MAX_SUBSCRIBER_BATCH

SessionFactory = Callable[[], AsyncSession]


async def reconcile_async(session_factory: SessionFactory, *, now: datetime) -> dict[str, int]:
    """One pass over every tenant's lists; ``{"lists", "suppressed", "failed"}``.

    ``now`` is the ``created_at`` of the rows this pass inserts. Runs with no
    tenant bound whatever the caller's scope: it is a platform pass that binds
    each tenant itself.
    """
    lists = inserted = failed = 0
    with no_tenant():
        async with session_factory() as session:
            tenants = await subscription_list_tenants(session)
        for tenant in tenants:
            with tenant_scope(tenant):
                try:
                    async with session_factory() as session:
                        keys = await subscription_lists(session, tenant_id=tenant)
                except Exception:
                    logger.warning(
                        "newsletter: could not read the lists of tenant %s; "
                        "its opt-outs wait for the next reconcile",
                        tenant,
                        exc_info=True,
                    )
                    failed += 1
                    continue
                for key in keys:
                    lists += 1
                    try:
                        inserted += await _reconcile_list(session_factory, tenant, key, now)
                    except Exception:
                        logger.warning(
                            "newsletter: could not reconcile list %r in tenant %s; "
                            "the next reconcile tries again",
                            key,
                            tenant,
                            exc_info=True,
                        )
                        failed += 1
    return {"lists": lists, "suppressed": inserted, "failed": failed}


async def _reconcile_list(
    session_factory: SessionFactory, tenant: str, key: str, now: datetime
) -> int:
    """Every opt-out of one list, page by page; rows inserted."""
    inserted = 0
    cursor: int | None = 0
    while cursor is not None:
        async with session_factory() as session:
            hits, cursor = await iter_subscribers(
                session,
                tenant_id=tenant,
                type_key=key,
                status="unsubscribed",
                include_trashed=True,
                limit=PAGE_SIZE,
                after=cursor,
            )
            # A subscriber with no address has nothing to suppress, and one
            # blank row must not fail the whole list every hour.
            emails = [hit.email for hit in hits if hit.email.strip()]
            if not emails:
                continue
            inserted += await suppress_many(
                session,
                tenant_id=tenant,
                emails=emails,
                reason=REASON_UNSUBSCRIBED,
                source=SOURCE,
                list_type_key=key,
                refresh=False,
                now=now,
            )
            await finalize_session(session)
    return inserted
