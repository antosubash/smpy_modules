"""Send the reminders of one tenant, claim first, inside budgets, never retrying.

For each candidate, in order (closest to stale first):

1. **denied** if the recipient is not eligible for this event now (:mod:`...recipients`), or the
   render step finds nothing the recipient may still see; nothing is claimed or spent;
2. **deferred** once any budget is closed: the per-tick send budget (install-wide), the tenant's
   share of it, the tick's wall-clock deadline, or the breaker (``REMINDER_BREAKER_FAILURES``
   consecutive failures: the transport is install-wide, so stop). A deferred candidate claims
   nothing and is found again on the next tick while it is inside the catch-up window;
3. the message is built **before** the claim: a rendering bug fails that one candidate and burns
   no claim, so it still goes out once fixed;
4. the claim (:mod:`~sm_events.reminders.claim`, committed) and ``begin_send`` (committed):
   **taken**
   when someone else has it or the event changed;
5. the transport is called under ``REMINDER_SEND_TIMEOUT``; success marks ``sent``, an exception
   or a timeout marks ``failed`` with ``send_failed``/``send_timeout``.

**A failed send is not retried, ever**: ``failed`` is final (at most once beats a late duplicate),
so a transient and a permanent failure are treated alike, and the breaker bounds what an outage can
write per tick (at most three ``failed`` rows). One failure never blocks the rest below the breaker.
A ``BaseException`` (a killed worker) propagates and leaves the row ``sending``: lost, never
repeated.

The log names the tenant, the event, the recipient's user id and the exception **class**: never
an address, a subject or an exception message (a relay's reply can quote the address).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_core.mail import MailMessage, MailSender

from sm_events.core import constants
from sm_events.core.constants import reminders_limits as limits
from sm_events.reminders import claim as ledger
from sm_events.reminders.candidates import Candidate
from sm_events.reminders.recipients import Eligibility
from sm_events.reminders.runtime import Recipient

__all__ = ["Budget", "SendCounts", "send_tenant"]

logger = logging.getLogger(__name__)

Render = Callable[[Candidate, Recipient], Awaitable[MailMessage | None]]


@dataclass
class Budget:
    remaining: int
    """Sends left in this tick, install-wide."""
    tenant_remaining: int
    """Sends left for the tenant being worked; reset to its share for each tenant."""
    deadline: float
    """``time.monotonic()`` after which nothing new is claimed."""
    failures_in_row: int = 0

    def open(self) -> bool:
        return (
            self.remaining > 0
            and self.tenant_remaining > 0
            and time.monotonic() < self.deadline
            and self.failures_in_row < limits.REMINDER_BREAKER_FAILURES
        )

    def open_overall(self) -> bool:
        """Is there install-wide budget, time and breaker left for another tenant pass?"""
        return (
            self.remaining > 0
            and time.monotonic() < self.deadline
            and self.failures_in_row < limits.REMINDER_BREAKER_FAILURES
        )

    def spend(self) -> None:
        self.remaining -= 1
        self.tenant_remaining -= 1


@dataclass
class SendCounts:
    sent: int = 0
    failed: int = 0
    denied: int = 0
    taken: int = 0
    deferred: int = 0
    stale: int = 0

    def add(self, other: SendCounts) -> None:
        for name in ("sent", "failed", "denied", "taken", "deferred", "stale"):
            setattr(self, name, getattr(self, name) + getattr(other, name))


async def _transport(
    factory: Any, tenant_id: str, c: Candidate, held: ledger.Claim, sender: MailSender,
    message: MailMessage, counts: SendCounts, budget: Budget, now: datetime,
) -> None:  # fmt: skip
    code: str | None = None
    try:
        await asyncio.wait_for(
            sender.send(message), timeout=limits.REMINDER_SEND_TIMEOUT.total_seconds()
        )
    except TimeoutError:
        code = constants.REMINDER_CODE_SEND_TIMEOUT
    except Exception as exc:  # the class only: a relay's reply can quote the address
        code = constants.REMINDER_SEND_FAILED
        logger.warning(
            "events: reminder send failed (%s) tenant=%s event=%s user=%s",
            type(exc).__name__, tenant_id, c.event_id, c.user_id,
        )  # fmt: skip
    if code is None:
        await ledger.mark_sent(factory, tenant_id, held.id, now=now)
        budget.failures_in_row = 0
        counts.sent += 1
        return
    if code == constants.REMINDER_CODE_SEND_TIMEOUT:
        logger.warning(
            "events: reminder send timed out tenant=%s event=%s user=%s",
            tenant_id, c.event_id, c.user_id,
        )  # fmt: skip
    await ledger.mark_failed(factory, tenant_id, held.id, code)
    budget.failures_in_row += 1
    counts.failed += 1


async def send_tenant(
    factory: Any,
    *,
    tenant_id: str,
    candidates: Sequence[Candidate],
    eligible: Eligibility,
    sender: MailSender,
    budget: Budget,
    render: Render,
    now: datetime,
) -> SendCounts:
    counts = SendCounts()
    for c in candidates:
        allowed = eligible.allowed.get(c.user_id)
        if allowed is None or c.event_id not in allowed[1]:
            counts.denied += 1
            continue
        if not budget.open():
            counts.deferred += 1
            continue
        who = allowed[0]
        try:
            message = await render(c, who)
        except Exception as exc:  # a bug in rendering: this one fails, nothing is claimed
            logger.warning(
                "events: reminder render failed (%s) tenant=%s event=%s",
                type(exc).__name__, tenant_id, c.event_id,
            )  # fmt: skip
            counts.failed += 1
            continue
        if message is None:
            counts.denied += 1
            continue
        held = await ledger.claim(factory, c, tenant_id=tenant_id, now=now)
        if held is None or not await ledger.begin_send(factory, tenant_id, held):
            counts.taken += 1
            continue
        budget.spend()
        await _transport(factory, tenant_id, c, held, sender, message, counts, budget, now)
    return counts
