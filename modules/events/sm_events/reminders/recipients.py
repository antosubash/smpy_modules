"""Who may still be reminded, decided at send time and failing closed.

For every ``(user, event)`` a reminder is about to go out for, this re-reads *current* state:

1. the runtime knows the account: active, a member of the tenant, rights derivable
   (:meth:`~sm_events.reminders.runtime.ReminderRuntime.recipients`); else ``not_resolvable``;
2. the account has a sendable address (one line, no whitespace or control characters; else
   ``no_email``) and the directory does not say it is unverified (a verified address where the
   directory reports one, as newsletter's test sends rule; ``email_verified is False`` is
   ``unverified_email``);
3. the principal holds ``events.view`` (else ``no_view``);
4. the event is among the published events that principal can see
   (:func:`~sm_events.core.access.events.visible_events`, ``include_unpublished=False``, one
   query per user); an event that is not is dropped for that user, and a user left with none is
   ``not_visible``.

Any exception from the runtime denies the whole batch (``resolver_error``) and logs its class,
never its message (it can quote an address). The counts are reasons only: no address, name or
id is ever logged here.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sm_events.core import constants
from sm_events.core.access.events import visible_events
from sm_events.models import Event
from sm_events.reminders.runtime import Recipient, ReminderRuntime

__all__ = ["DENY_REASONS", "Eligibility", "eligible"]

logger = logging.getLogger(__name__)

DENY_REASONS = (
    "not_resolvable",
    "no_email",
    "unverified_email",
    "no_view",
    "not_visible",
    "resolver_error",
)


@dataclass
class Eligibility:
    allowed: dict[str, tuple[Recipient, set[uuid.UUID]]] = field(default_factory=dict)
    """``user -> (recipient, the wanted events they may see now)``."""
    denied: dict[str, int] = field(default_factory=dict)
    """Users refused, by reason code."""


def _sendable(email: str) -> bool:
    return (
        bool(email)
        and "@" in email
        and email == email.strip()
        and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in email)
    )


async def eligible(
    db: Any,
    runtime: ReminderRuntime,
    *,
    tenant_id: str,
    wanted: Mapping[str, set[uuid.UUID]],
) -> Eligibility:
    out = Eligibility()
    if not wanted:
        return out
    denied: Counter[str] = Counter()
    try:
        found = await runtime.recipients(db, tenant_id=tenant_id, user_ids=list(wanted))
    except Exception as exc:  # the class only: a message can quote an address
        logger.warning("events: reminder recipients unavailable (%s)", type(exc).__name__)
        out.denied = {"resolver_error": len(wanted)}
        return out
    for user_id, events in wanted.items():
        who = found.get(user_id)
        if who is None:
            denied["not_resolvable"] += 1
        elif not _sendable(who.email):
            denied["no_email"] += 1
        elif who.verified is False:
            denied["unverified_email"] += 1
        elif not who.principal.has(constants.PERM_VIEW):
            denied["no_view"] += 1
        else:
            seen = await _visible(db, who, events)
            if seen:
                out.allowed[user_id] = (who, seen)
            else:
                denied["not_visible"] += 1
    out.denied = dict(denied)
    return out


async def _visible(db: Any, who: Recipient, events: set[uuid.UUID]) -> set[uuid.UUID]:
    if not events:
        return set()
    stmt = visible_events(who.principal, include_unpublished=False).where(
        Event.id.in_(events)  # type: ignore[attr-defined]
    )
    return {row.id for row in (await db.execute(stmt)).scalars()}
