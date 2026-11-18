"""From a presented token to what its owner may see right now.

:func:`lookup` is the module's one narrow cross-tenant read (the token's hash is the whole
predicate); everything after it runs in the row's tenant, in :func:`resolve`, which asks the
current state of the world on every call and keeps nothing: the row is not revoked, the host
does not contradict its tenant, the owner is an active member with known roles, and the
calendar is in what that principal may view. A refusal is ``None``, whatever the reason.

**Every check is evaluated** (no early return) so a refusal does the same work whichever check
failed: nothing about *why* a token stopped working shows in how long the answer took. A
missing row alone ends it, since there is nothing to evaluate.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from simple_module_db import all_tenants as unscoped
from simple_module_db import finalize_session
from sqlalchemy import or_, select, update

from sm_events.core import constants
from sm_events.core.access import visible_calendars
from sm_events.core.access.events import visible_events
from sm_events.core.access.offline import offline_principal
from sm_events.core.access.public import ANONYMOUS
from sm_events.core.tenancy import all_tenants, tenant_scope
from sm_events.feeds.tokens.codec import hash_token
from sm_events.models import Calendar, Event, FeedToken

__all__ = ["FeedAccess", "TokenRow", "lookup", "resolve", "touch_last_used"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenRow:
    """What the hash lookup returns: enough to bind the tenant and ask the questions, never the
    digest."""

    id: uuid.UUID
    tenant_id: str
    calendar_id: uuid.UUID
    user_id: str
    locale: str
    revoked: bool


@dataclass(frozen=True)
class FeedAccess:
    """A token that passed every check, and the principal and calendar it serves."""

    row: TokenRow
    who: ResourcePrincipal
    calendar: Calendar

    def events(self) -> Any:
        """The one select a private feed reads from: **published** events of this calendar
        that its owner may see. Never drafts or scheduled events, even for an owner who may
        write them: a feed is a copy that leaves the console's access control."""
        return visible_events(self.who, include_unpublished=False).where(
            Event.calendar_id == self.row.calendar_id
        )


async def lookup(db: Any, token: str) -> TokenRow | None:
    """The row whose digest is ``hash_token(token)``, across every tenant, in one statement.

    The only cross-tenant read of the request path: its sole predicate is the digest (a
    unique, 256-bit-derived value), and it selects no column that names the token."""
    stmt = all_tenants(
        select(
            FeedToken.id,
            FeedToken.tenant_id,
            FeedToken.calendar_id,
            FeedToken.user_id,
            FeedToken.locale,
            FeedToken.revoked_at,
        ).where(FeedToken.token_hash == hash_token(token))  # type: ignore[arg-type]
    )
    with unscoped():
        found = (await db.execute(stmt)).first()
    if found is None:
        return None
    return TokenRow(
        id=found.id,
        tenant_id=found.tenant_id,
        calendar_id=found.calendar_id,
        user_id=found.user_id,
        locale=found.locale,
        revoked=found.revoked_at is not None,
    )


async def resolve(
    app: Any, db: Any, request: Any, row: TokenRow | None, *, host_tenant: str | None
) -> FeedAccess | None:
    """What ``row``'s owner may see now, or ``None``. Called with the row's tenant bound.

    ``host_tenant`` is the tenant the request's *host* resolved (a subdomain), which must not
    contradict the row's; one a visitor chose (session, header) proves nothing and is never
    passed."""
    if row is None:
        return None
    who = await offline_principal(
        app, db, user_id=row.user_id, tenant_id=row.tenant_id, request=request
    )
    # Asked even without a principal (as the anonymous one, who sees public calendars only),
    # so a refusal costs the same statements whatever its reason.
    stmt = visible_calendars(who or ANONYMOUS).where(
        Calendar.id == row.calendar_id,
        Calendar.tenant_id == row.tenant_id,  # type: ignore[arg-type]
    )
    calendar = (await db.execute(stmt)).scalar_one_or_none()
    checks = [
        not row.revoked,
        host_tenant is None or host_tenant == row.tenant_id,
        who is not None,
        calendar is not None,
    ]
    if not all(checks) or who is None or calendar is None:
        return None
    return FeedAccess(row=row, who=who, calendar=calendar)


async def touch_last_used(factory: Any, row: TokenRow, *, now: datetime) -> None:
    """Note that the link was used, at most once an hour, in a session of its own.

    No lock is held while the feed is built, two concurrent fetches write at most once, and
    any failure is logged by class and ignored: the feed has been served already."""
    table = FeedToken.__table__
    stale = now - constants.FEED_LAST_USED_GRANULARITY
    try:
        with tenant_scope(row.tenant_id):
            async with factory() as session:
                await session.execute(
                    update(table)
                    .where(
                        table.c.tenant_id == row.tenant_id,
                        table.c.id == row.id,
                        or_(table.c.last_used_at.is_(None), table.c.last_used_at < stale),
                    )
                    .values(last_used_at=now)
                )
                await finalize_session(session)
    except Exception as exc:  # never the message: it can carry the address
        logger.warning("events: could not record a private feed use (%s)", type(exc).__name__)
