"""One reminder pass: what the ``events.reminders`` beat does.

A platform pass (no tenant bound by the caller), safe to run twice, late, or never:

1. **Settings** are read the way a worker reads them (``background_tasks.settings_for``, cached
   about 30 s); nothing happens while ``reminders_enabled`` is off.
2. **The runtime** (the worker's headless app, or the live app when run eagerly) and the mail
   sender are resolved once. Anything missing (no runtime, no base URL, no transport, a sender
   that only logs) means nothing is sent and the pass says ``unavailable``: availability is
   checked again here, in the process that sends.
3. **One narrow read** lists the tenants that have followers, tagged for events' own guard *and*
   inside the framework's ``all_tenants()``, which strict isolation asks for. Each tenant is then
   worked in sessions of its own under its own tenant scope; one tenant's exception is logged by
   class, counted and does not stop the others.
4. **Fairness and bounds.** Tenants are served in an order that rotates every minute, each with
   its share (``REMINDER_TENANT_BUDGET``) of the pass's ``REMINDER_SEND_BUDGET`` and all of them
   inside ``REMINDER_TICK_BUDGET`` seconds, so no tenant starves another; what is not reached is
   found again on the next pass while it is inside its catch-up window (and never after).
5. Per tenant: candidates (:mod:`.candidates`), who may still be reminded (:mod:`.recipients`),
   then :func:`~sm_events.reminders.send.send_tenant`. Each message is built from the event as the
   recipient may see it **just now**, re-read through that recipient's own principal.

Claims are the only arbiter: there is no tick lock to leak, and two beats running together send
each reminder once. A host without a beat never sends reminders and nothing piles up: only what
is inside the catch-up window is ever a candidate.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from simple_module_core.mail import mail_transport_installed, resolve_mail_sender
from simple_module_db import all_tenants as framework_all_tenants
from simple_module_db import finalize_session
from sqlalchemy import distinct, select

from sm_events.core import constants, public_prefix
from sm_events.core.access.events import visible_events
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import all_tenants, bound_tenant, tenant_scope
from sm_events.models import Calendar, Event, EventFollow, EventText
from sm_events.reminders import candidates, limits, recipients, send
from sm_events.reminders.links import Links
from sm_events.reminders.message import build_message
from sm_events.reminders.runtime import Recipient, ReminderRuntime

__all__ = ["bound_tenant", "order_tenants", "reminders_async"]

logger = logging.getLogger(__name__)

_COUNTS = ("sent", "failed", "denied", "taken", "deferred")


def _stored_settings() -> EventsSettings:
    """The stored settings as a worker reads them (synchronous, cached for 30 s)."""
    from background_tasks import settings_for

    return settings_for(EventsSettings, constants.PACKAGE, ttl=30)


def order_tenants(tenants: list[str], now: datetime) -> list[str]:
    """Rotate the order by the minute, so the tenant served first changes every pass."""
    if not tenants:
        return []
    ordered = sorted(tenants)
    shift = int(now.timestamp() // 60) % len(ordered)
    return ordered[shift:] + ordered[:shift]


async def _tenants(factory: Any) -> list[str]:
    stmt = all_tenants(select(distinct(EventFollow.tenant_id)))
    with framework_all_tenants():
        async with factory() as session:
            found = sorted((await session.execute(stmt)).scalars())
            await finalize_session(session)
    return found


def _unavailable(runtime: ReminderRuntime, sender: Any) -> str | None:
    """Why this process cannot send, as a stable code, or ``None``."""
    reasons = constants.AVAILABILITY_REASONS
    if not runtime.public_base_url:
        return reasons[1]
    if not mail_transport_installed():
        return reasons[2]
    if not sender.delivers_email:
        return reasons[3]
    return None


def _renderer(factory: Any, links: Links, default_locale: str) -> Any:
    async def render(c: candidates.Candidate, who: Recipient) -> Any:
        async with factory() as db:
            stmt = visible_events(who.principal, include_unpublished=False).where(
                Event.id == c.event_id  # type: ignore[arg-type]
            )
            event = (await db.execute(stmt)).scalar_one_or_none()
            if event is None or event.cancelled or event.revision != c.revision:
                return None
            calendar = (
                await db.execute(select(Calendar).where(Calendar.id == event.calendar_id))  # type: ignore[arg-type]
            ).scalar_one_or_none()
            if calendar is None:
                return None
            texts = {
                t.locale: t
                for t in (
                    await db.execute(select(EventText).where(EventText.event_id == event.id))  # type: ignore[arg-type]
                ).scalars()
            }
            await finalize_session(db)
        return build_message(
            to=who.email,
            event=event,
            texts=texts,
            calendar=calendar,
            occurrence_start=c.start,
            occurrence_end=c.end,
            lead=c.lead,
            locale=c.locale,
            default_locale=default_locale,
            links=links,
            moved_from=c.moved_from,
        )

    return render


async def _tenant(
    factory: Any, tenant: str, runtime: ReminderRuntime, sender: Any, budget: send.Budget,
    settings: EventsSettings, now: datetime,
) -> send.SendCounts:  # fmt: skip
    with tenant_scope(tenant):
        async with factory() as db:
            found, deferred = await candidates.candidates(db, now=now)
            wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
            for c in found:
                wanted[c.user_id].add(c.event_id)
            eligible = await recipients.eligible(db, runtime, tenant_id=tenant, wanted=wanted)
            await finalize_session(db)
        counts = send.SendCounts(deferred=deferred)
        if found:
            locales = tuple(settings.content_locales) or ("en",)
            links = Links(
                base_url=runtime.public_base_url,
                prefix=public_prefix.effective(settings.public_prefix),
                content_locales=locales,
                single_tenant=runtime.single_tenant,
            )
            counts.add(
                await send.send_tenant(
                    factory,
                    tenant_id=tenant,
                    candidates=found,
                    eligible=eligible,
                    sender=sender,
                    budget=budget,
                    now=now,
                    render=_renderer(factory, links, locales[0]),
                )
            )
    return counts


async def reminders_async(
    factory: Any,
    *,
    runtime_factory: Any,
    now: datetime,
    settings: EventsSettings | None = None,
) -> dict[str, int]:
    """One pass; ``{tenants, sent, failed, denied, taken, deferred, tenants_failed,
    unavailable}``."""
    summary = {"tenants": 0, **dict.fromkeys(_COUNTS, 0), "tenants_failed": 0, "unavailable": 0}
    settings = settings or await asyncio.to_thread(_stored_settings)
    if not settings.reminders_enabled:
        return summary
    async with factory() as db:
        runtime = await runtime_factory(db)
        sender = await resolve_mail_sender(db) if runtime is not None else None
        await finalize_session(db)
    why = "no_runtime" if runtime is None else _unavailable(runtime, sender)
    if why is not None or runtime is None:
        summary["unavailable"] = 1
        logger.info("events.reminders: nothing sent (%s)", why)
        return summary
    budget = send.Budget(
        remaining=limits.REMINDER_SEND_BUDGET,
        tenant_remaining=limits.REMINDER_TENANT_BUDGET,
        deadline=time.monotonic() + limits.REMINDER_TICK_BUDGET.total_seconds(),
    )
    for tenant in order_tenants(await _tenants(factory), now):
        summary["tenants"] += 1
        budget.tenant_remaining = min(limits.REMINDER_TENANT_BUDGET, budget.remaining)
        try:
            counts = await _tenant(factory, tenant, runtime, sender, budget, settings, now)
        except Exception as exc:  # one tenant never stops the rest; the class only
            logger.warning("events.reminders: a tenant failed (%s)", type(exc).__name__)
            summary["tenants_failed"] += 1
            continue
        for name in _COUNTS:
            summary[name] += getattr(counts, name)
    logger.info(
        "events.reminders: %d tenant(s), %d sent, %d failed, %d denied, %d taken, %d deferred",
        summary["tenants"], summary["sent"], summary["failed"], summary["denied"],
        summary["taken"], summary["deferred"],
    )  # fmt: skip
    return summary
