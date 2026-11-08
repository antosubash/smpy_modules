"""Records' ``SubscriptionChanged`` mirrored into the suppression store.

Records publishes the event after its commit, in the tenant it describes
(``sm_records.core.events``), through the in-process bus, which awaits every
handler and logs - never propagates - a failure. This handler is a fast path
only: the hourly reconcile re-reads records' opt-outs anyway, so a lost or
failed opt-out costs latency, not correctness; a lost confirmation leaves the
address suppressed (fail-safe). That is why the handler never raises.

**The event is a hint, records is the truth.** It carries identifiers only;
:func:`apply` reads the subscriber back (``subscribers_by_uuid``, any status,
trashed included) and acts only when the current status still equals the
event's ``status_after`` - a stale event (the subscriber moved on since) does
nothing:

* ``unsubscribed`` (trashed or not: a trashed opt-out is still an opt-out) -
  the list's ``unsubscribed`` row, its ``created_at`` refreshed on repeat but
  its ``source`` kept (a page opt-out stays ``unsubscribe_page``), ``"suppressed"``.
* ``pending -> confirmed`` - a double-opt-in confirmation (records' confirm
  link) - and not trashed, with a ``confirmed_at``: the clear a confirmation
  lifts, cut off at that time so a bounce recorded after it survives a delayed
  handler; ``"cleared"`` whenever the clear ran, even if it deleted nothing.
  Without a ``confirmed_at`` nothing is cleared.
* anything else (pending, unknown uuid, not a list, and every other way to
  ``confirmed``) - ``"ignored"``.

**Only the confirm link clears.** It is the one change that proves the address
reached its owner: the link is mailed to it, and records' ``opt_in.confirm`` is
the only ``pending -> confirmed`` transition it announces. A new address on a
single-opt-in list is ``None -> confirmed`` at once - anyone can type a
victim's address into the form, so it must not erase that address's bounces or
opt-outs. Records sends a known address back to ``pending``, never straight to
``confirmed``, and its admin screens and imports cannot write ``sm_status``. A
future records path that confirms without the link must not announce
``pending -> confirmed``, or must carry a signal this handler can tell apart.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

from simple_module_core.events import EventBus
from simple_module_db import finalize_session
from sm_records.contracts.events import SubscriptionChanged
from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    SubscriberHit,
    subscribers_by_uuid,
)
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.constants import REASON_UNSUBSCRIBED
from sm_newsletter.core.suppression.store import clear_for_confirmation, suppress
from sm_newsletter.core.tenancy import tenant_scope

__all__ = ["Outcome", "apply", "subscribe"]

logger = logging.getLogger(__name__)

Outcome = Literal["suppressed", "cleared", "ignored"]

SOURCE = "records_event"

# What a failed mirror costs, per ``status_after``: the reconcile only re-adds
# opt-outs, so a lost confirmation's clear stays undone (fail-safe: the address
# remains suppressed).
_AFTER_FAILURE = {
    "unsubscribed": "the hourly reconcile picks it up",
    "confirmed": "the address stays suppressed: the reconcile never clears",
}


async def apply(event: SubscriptionChanged, session_factory: Callable[[], AsyncSession]) -> Outcome:
    """Mirror one event in a session of its own, bound to the event's tenant."""
    tenant = event.tenant_id
    with tenant_scope(tenant):
        async with session_factory() as session:
            try:
                hits = await subscribers_by_uuid(
                    session, tenant_id=tenant, type_key=event.type_key, uuids=[event.uuid]
                )
            except SubscriberFilterError:
                return "ignored"  # the type is not (or no longer) a newsletter list
            hit = hits.get(event.uuid)
            if hit is None or hit.status != event.status_after:
                return "ignored"
            outcome = await _act(session, event, hit)
            if outcome != "ignored":
                await finalize_session(session)
            return outcome


async def _act(session: AsyncSession, event: SubscriptionChanged, hit: SubscriberHit) -> Outcome:
    if hit.status == "unsubscribed":
        await suppress(
            session,
            tenant_id=event.tenant_id,
            email=hit.email,
            reason=REASON_UNSUBSCRIBED,
            source=SOURCE,
            list_type_key=event.type_key,
            keep_source=True,  # the first writer's source stands (a page opt-out)
        )
        return "suppressed"
    if _link_confirmation(event) and not hit.trashed and hit.confirmed_at is not None:
        await clear_for_confirmation(
            session,
            tenant_id=event.tenant_id,
            email=hit.email,
            list_type_key=event.type_key,
            confirmed_at=hit.confirmed_at,
        )
        return "cleared"
    return "ignored"


def _link_confirmation(event: SubscriptionChanged) -> bool:
    """Whether the event is records' confirm link: ``pending -> confirmed``."""
    return event.status_before == "pending" and event.status_after == "confirmed"


def subscribe(bus: EventBus, app: Any) -> None:
    """Subscribe the mirror. The session factory is read when an event
    arrives, not now: ``app.state.sm.db`` is the running app's."""

    async def _mirror(event: SubscriptionChanged) -> None:
        try:
            await apply(event, app.state.sm.db.session_factory)
        except Exception:
            logger.warning(
                "newsletter: could not mirror %s -> %s for list %r in tenant %s; %s",
                event.status_before,
                event.status_after,
                event.type_key,
                event.tenant_id,
                _AFTER_FAILURE.get(event.status_after, "nothing else retries it"),
                exc_info=True,
            )

    bus.subscribe(SubscriptionChanged, _mirror)
