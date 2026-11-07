"""The dispatcher tick: freeze what is due, then spend the budget in slices (S6, S7, S12).

One tick, run with no tenant bound:

1. :func:`~.upkeep.recover_expired` (a dead sender's rows, S7), then
   :func:`~.freeze.start_due`. On the ``smtp`` transport a snapshot that is
   not ``https://`` (A6: the transport may have changed since it was
   scheduled) pauses a due campaign at freeze, before anything is frozen, and
   :func:`~.upkeep.pause_insecure` pauses one already ``sending``.
2. Nothing ``sending``, or no budget left: :func:`~.upkeep.finish_done`, and
   no relay connection (a capped day neither logs in every minute nor lets a
   refused login pause every campaign).
3. One transport session for the whole tick. A refused login pauses every
   ``sending`` campaign (``smtp_auth``); any other failure only ends the tick.
4. Slices until :data:`TICK_SECONDS`, each inside the dispatch lock: read the
   budget, send at most ``min(budget.left, SLICE)`` (oldest-started campaign
   first, across tenants), release. A test send waits at most one slice.
5. :func:`~.upkeep.finish_done`.

A verdict that stops the tick (a relay quota reply, a relay refusal) ends it
after that recipient; a list gone pauses only its campaign. A slice also ends
after :data:`MAX_SLICE_STEPS` recipients, skips included. A lost or busy lock
ends the tick with nothing reserved.
"""

from __future__ import annotations

import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass

from sm_newsletter.core import constants
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import DispatchBusy, TransportUnavailable
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.sending.budget import current_budget
from sm_newsletter.sending.deliver import Step, deliver_one
from sm_newsletter.sending.freeze import Clock, start_due
from sm_newsletter.sending.lock import HeldLock, dispatch_lock
from sm_newsletter.sending.transport import Transport, TransportSession
from sm_newsletter.sending.upkeep import (
    SessionFactory,
    finish_done,
    pause_all_sending,
    pause_insecure,
    recover_expired,
    sending_campaigns,
)

__all__ = ["HOLDER", "MAX_SLICE_STEPS", "SLICE", "TICK_SECONDS", "TickSummary", "tick"]

logger = logging.getLogger(__name__)

SLICE = 10
MAX_SLICE_STEPS = SLICE * 5
"""Recipients a slice may pass over (skips included) before it releases the
lock, so a run of skipped rows never keeps a test send waiting a whole tick."""
TICK_SECONDS = 50.0
HOLDER = "dispatcher"


@dataclass
class TickSummary:
    started: int = 0
    spent: int = 0
    skipped: int = 0
    recovered: int = 0
    finished: int = 0
    paused: int = 0
    stopped: str | None = None
    """``idle``, ``budget``, ``busy``, ``relay``, ``transport_unavailable``,
    ``deadline`` or ``not_configured`` (the worker's refusal, S12)."""


@dataclass
class _Run:
    factory: SessionFactory
    settings: NewsletterSettings
    secret: str
    smtp: TransportSession
    list_unsubscribe: bool
    clock: Clock
    deadline: float
    summary: TickSummary

    def late(self) -> bool:
        return time.monotonic() >= self.deadline


async def tick(
    factory: SessionFactory,
    *,
    settings: NewsletterSettings,
    secret: str,
    transport: Transport,
    clock: Clock = utcnow,
    deadline_s: float = TICK_SECONDS,
    lock_wait_s: float = 15,
) -> TickSummary:
    """One dispatcher pass; what it did and why it stopped."""
    deadline = time.monotonic() + deadline_s
    summary = TickSummary()
    summary.recovered = await recover_expired(factory, now=clock())
    smtp_only = settings.transport == "smtp"
    summary.started = await start_due(factory, now=clock(), clock=clock, require_https=smtp_only)
    if smtp_only:  # the campaigns already sending when the transport changed
        summary.paused += await pause_insecure(factory, now=clock())
    if not await sending_campaigns(factory):
        summary.stopped = "idle"
    elif (await current_budget(factory, settings, now=clock())).left == 0:
        summary.stopped = "budget"  # a capped day neither logs in nor auth-pauses
    if summary.stopped is not None:
        summary.finished = await finish_done(factory, now=clock())
        return summary
    async with AsyncExitStack() as stack:
        try:
            smtp = await stack.enter_async_context(transport.session())
        except TransportUnavailable as exc:
            logger.warning("newsletter: the mail relay is unavailable (%s)", exc.stage)
            if exc.stage != "auth":
                summary.stopped = "transport_unavailable"
                return summary
            summary.paused += await pause_all_sending(
                factory, code=constants.PAUSE_SMTP_AUTH, detail=exc.detail, now=clock()
            )
            summary.stopped = "relay"
            return summary
        run = _Run(
            factory,
            settings,
            secret,
            smtp,
            transport.supports_list_unsubscribe,
            clock,
            deadline,
            summary,
        )
        summary.stopped = await _slices(run, lock_wait_s)
    summary.finished = await finish_done(factory, now=clock())
    return summary


async def _slices(run: _Run, lock_wait_s: float) -> str:
    """Slices until one says why the tick stops."""
    while not run.late():
        try:
            async with dispatch_lock(run.factory, holder=HOLDER, wait_s=lock_wait_s) as lock:
                stopped = await _slice(run, lock)
        except DispatchBusy:
            return "busy"
        if stopped is not None:
            return stopped
    return "deadline"


async def _slice(run: _Run, lock: HeldLock) -> str | None:
    """Up to ``min(budget.left, SLICE)`` counted attempts; why the tick stops,
    or ``None`` when the slice is done and the next one may start."""
    budget = await current_budget(run.factory, run.settings, now=run.clock())
    n = min(budget.left, SLICE)
    if n == 0:
        return "budget"
    spent = steps = 0
    campaigns = await sending_campaigns(run.factory)  # a campaign that has nothing
    while spent < n:  # to send now leaves the list until the next slice
        if run.late():
            return "deadline"
        if steps >= MAX_SLICE_STEPS:
            return None
        steps += 1
        step = await _next(run, lock, campaigns)
        if step is None:
            return "idle"
        verdict = step.verdict
        spent += int(step.spent)
        run.summary.spent += int(step.spent)
        run.summary.skipped += int(verdict.action == "skip")
        run.summary.paused += int(verdict.action == "pause")
        if verdict.stop_tick:
            return "relay"
    return None


async def _next(run: _Run, lock: HeldLock, campaigns: list[tuple[str, int]]) -> Step | None:
    """One recipient of the oldest-started campaign that has one due."""
    while campaigns:
        tenant, campaign_id = campaigns[0]
        step = await deliver_one(
            run.factory,
            run.smtp,
            lock,
            tenant_id=tenant,
            campaign_id=campaign_id,
            secret=run.secret,
            list_unsubscribe=run.list_unsubscribe,
            clock=run.clock,
            require_https=run.settings.transport == "smtp",
        )
        if step is not None:
            return step
        campaigns.pop(0)
    return None
