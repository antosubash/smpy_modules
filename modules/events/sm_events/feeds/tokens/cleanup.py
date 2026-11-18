"""Remove private feed links when what they stand for is gone.

**Correctness never depends on this.** A link whose user, membership or tenant is gone serves
nothing already: :func:`~sm_events.feeds.tokens.resolve.resolve` asks the directory and the
membership store on every request. These handlers only remove the rows, so a deleted account
does not leave a hash table behind. They run in the web process (the framework's in-process
bus); an event missed (a restart, another process) leaves a row that still serves nothing, and
the janitor's :func:`sweep_revoked` is the only scheduled removal.

* ``UserDeleted``: every link of that user, in every tenant. The one handler here that reads
  across tenants, with its own ``user_id`` predicate and nothing else.
* ``MembershipRemoved``: that user's links in that tenant.
* ``TenantDeleted``: every link of that tenant.

Each opens a session of its own, finishes it with ``finalize_session``, and on failure logs the
exception class (its message can quote an id) and swallows it: a cleanup must never break the
event that triggered it.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from simple_module_db import all_tenants as unscoped
from simple_module_db import finalize_session
from sqlalchemy import delete, func

from sm_events.core import constants
from sm_events.core.tenancy import bound_tenant, tenant_scope, valid_tenant
from sm_events.models import FeedToken

__all__ = [
    "delete_member_tokens",
    "delete_tenant_tokens",
    "delete_user_tokens",
    "subscribe",
    "sweep_revoked",
]

logger = logging.getLogger(__name__)

_TABLE = FeedToken.__table__


def _spellings(user_id: uuid.UUID | str) -> tuple[str, ...]:
    """Every way a user id is written (lower case, hyphenated or bare) that a link could hold."""
    text = str(user_id).lower()
    return (text, text.replace("-", ""))


async def _run(
    factory: Callable[[], Any],
    statement: Any,
    scope: AbstractContextManager[Any],
) -> int:
    with scope:
        async with factory() as session:
            removed = (await session.execute(statement)).rowcount
            await finalize_session(session)
    return int(removed or 0)


async def delete_user_tokens(factory: Callable[[], Any], user_id: uuid.UUID | str) -> int:
    """Every link of ``user_id`` in every tenant: the one narrow cross-tenant delete, whose only
    predicate is the user."""
    statement = delete(_TABLE).where(func.lower(_TABLE.c.user_id).in_(_spellings(user_id)))
    return await _run(factory, statement, unscoped())


async def delete_member_tokens(factory: Callable[[], Any], tenant_id: str, user_id: str) -> int:
    """``user_id``'s links in ``tenant_id`` only. An id that cannot be a tenant deletes nothing."""
    if not valid_tenant(tenant_id):
        return 0
    statement = delete(_TABLE).where(
        _TABLE.c.tenant_id == tenant_id,
        func.lower(_TABLE.c.user_id).in_(_spellings(user_id)),
    )
    return await _run(factory, statement, tenant_scope(tenant_id))


async def delete_tenant_tokens(factory: Callable[[], Any], tenant_id: str) -> int:
    if not valid_tenant(tenant_id):
        return 0
    statement = delete(_TABLE).where(_TABLE.c.tenant_id == tenant_id)
    return await _run(factory, statement, tenant_scope(tenant_id))


async def sweep_revoked(db: Any, *, now: datetime) -> int:
    """Delete links revoked more than ``FEED_REVOKED_KEPT_DAYS`` ago, in the bound tenant.
    Called per tenant by the janitor (a Core statement: it carries its own tenant predicate)."""
    cutoff = now - timedelta(days=constants.FEED_REVOKED_KEPT_DAYS)
    statement = delete(_TABLE).where(
        _TABLE.c.tenant_id == bound_tenant(),
        _TABLE.c.revoked_at.is_not(None),
        _TABLE.c.revoked_at < cutoff,
    )
    return int((await db.execute(statement)).rowcount or 0)


def _guarded(
    app: Any, label: str, work: Callable[[Any, Any], Awaitable[int]]
) -> Callable[[Any], Awaitable[None]]:
    async def handler(event: Any) -> None:
        try:
            removed = await work(app.state.sm.db.session_factory, event)
        except Exception as exc:  # the class only; the message can quote an id
            logger.warning("events: TokenCleanup failed (%s)", type(exc).__name__)
            return
        if removed:
            logger.info("events: removed %d private feed link(s) (%s)", removed, label)

    return handler


def subscribe(bus: Any, app: Any) -> None:
    """Subscribe the three handlers; an event class the installed framework lacks is skipped
    with a log line (the others still apply)."""
    try:
        from simple_module_core.user_events import UserDeleted

        bus.subscribe(
            UserDeleted,
            _guarded(app, "user deleted", lambda f, e: delete_user_tokens(f, e.user_id)),
        )
    except ImportError:
        logger.info("events: this framework has no UserDeleted; links go with the janitor only")
    try:
        from tenants.contracts.events import MembershipRemoved

        bus.subscribe(
            MembershipRemoved,
            _guarded(
                app,
                "membership removed",
                lambda f, e: delete_member_tokens(f, e.tenant_id, e.user_id),
            ),
        )
    except ImportError:
        logger.info(
            "events: no MembershipRemoved here; links of a removed member stop serving anyway"
        )
    try:
        from simple_module_core.tenant_events import TenantDeleted

        bus.subscribe(
            TenantDeleted,
            _guarded(app, "tenant deleted", lambda f, e: delete_tenant_tokens(f, e.tenant_id)),
        )
    except ImportError:
        logger.info("events: this framework has no TenantDeleted; its links stop serving anyway")
