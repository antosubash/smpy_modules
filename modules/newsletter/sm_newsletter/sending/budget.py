"""The rolling send budget: the last 24 hours and the last 60 seconds.

Both windows count the ledger's attempts across every tenant
(:func:`~sm_newsletter.sending.ledger.attempts_since`) against the
``daily_limit`` and ``per_minute_limit`` settings. Admission is all-or-nothing
(:func:`admit`): a send of ``n`` either fits both windows whole or is refused
with nothing sent. Call it inside the dispatch lock, or two senders can both
fit the same room.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sm_newsletter.core.errors import SendBudgetExhausted
from sm_newsletter.sending.ledger import SessionFactory, attempts_since

if TYPE_CHECKING:
    from sm_newsletter.core.settings import NewsletterSettings

__all__ = ["DAY", "MINUTE", "Budget", "admit", "current_budget"]

DAY = timedelta(hours=24)
MINUTE = timedelta(seconds=60)


@dataclass(frozen=True)
class Budget:
    day_used: int
    minute_used: int
    daily_limit: int
    per_minute_limit: int

    @property
    def left(self) -> int:
        """How many more fit both windows now."""
        return max(
            0, min(self.daily_limit - self.day_used, self.per_minute_limit - self.minute_used)
        )

    def fits(self, n: int) -> bool:
        return (
            self.day_used + n <= self.daily_limit and self.minute_used + n <= self.per_minute_limit
        )


async def current_budget(
    session_factory: SessionFactory, settings: NewsletterSettings, *, now: datetime
) -> Budget:
    """Both windows as of ``now`` (an attempt exactly at a window's edge counts)."""
    return Budget(
        day_used=await attempts_since(session_factory, since=now - DAY),
        minute_used=await attempts_since(session_factory, since=now - MINUTE),
        daily_limit=settings.daily_limit,
        per_minute_limit=settings.per_minute_limit,
    )


async def admit(
    session_factory: SessionFactory, settings: NewsletterSettings, *, n: int, now: datetime
) -> Budget:
    """The budget before a send of ``n``; :class:`SendBudgetExhausted` unless all ``n`` fit."""
    budget = await current_budget(session_factory, settings, now=now)
    if not budget.fits(n):
        raise SendBudgetExhausted()
    return budget
