"""The numeric bounds of reminders: one place, so a test can pin each at its edge."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Final

__all__ = [
    "FOLLOWS_PER_USER",
    "FOLLOW_RATE",
    "LEDGER_DAYS",
    "LEDGER_PRUNE_BATCH",
    "LEDGER_PRUNE_MAX_BATCHES",
    "MAX_LEAD_MINUTES",
    "MINE_PAGE_MAX",
    "MINE_PAGE_SIZE",
    "REMINDER_BREAKER_FAILURES",
    "REMINDER_CANDIDATES_MAX",
    "REMINDER_CATCHUP",
    "REMINDER_CLAIM_LEASE",
    "REMINDER_EARLY",
    "REMINDER_LEADS",
    "REMINDER_RUNTIME_TTL",
    "REMINDER_SEND_BUDGET",
    "REMINDER_SEND_TIMEOUT",
    "REMINDER_SUBJECT_MAX",
    "REMINDER_TENANT_BUDGET",
    "REMINDER_TICK_BUDGET",
    "REMINDER_TICK_SECONDS",
    "REMINDER_UNFINISHED_AFTER",
    "STATS_WINDOW_DAYS",
]

# Following (Rulings 6 and 8).
REMINDER_LEADS: Final = (15, 60, 1440, 10080)
"""The allowed lead times in minutes: 15 minutes, 1 hour, 1 day, 1 week. A closed set."""
MAX_LEAD_MINUTES: Final = 10080
FOLLOWS_PER_USER: Final = 200
"""Distinct followed events per user and tenant; re-saving a followed event does not count."""
FOLLOW_RATE: Final = "30/minute"
MINE_PAGE_SIZE: Final = 50
MINE_PAGE_MAX: Final = 100

# The due rule (Ruling 14).
REMINDER_EARLY: Final = timedelta(seconds=60)
"""One beat: a punctual tick is never late, at most one tick early."""
REMINDER_CATCHUP: Final[Mapping[int, timedelta]] = {
    15: timedelta(minutes=5),
    60: timedelta(minutes=15),
    1440: timedelta(hours=6),
    10080: timedelta(hours=6),
}
"""How late a reminder may still go out; later than this it is stale and never sent."""

# The beat (Rulings 13, 15, 18, 21, 22).
REMINDER_TICK_SECONDS: Final = 60
REMINDER_CANDIDATES_MAX: Final = 5000
REMINDER_SEND_BUDGET: Final = 300
REMINDER_TENANT_BUDGET: Final = 100
REMINDER_TICK_BUDGET: Final = timedelta(seconds=45)
REMINDER_BREAKER_FAILURES: Final = 3
REMINDER_SEND_TIMEOUT: Final = timedelta(seconds=30)
REMINDER_CLAIM_LEASE: Final = timedelta(minutes=2)
"""How long a ``claimed`` row (committed, SMTP not yet begun) belongs to its claimer; after that it
may be reclaimed, because a row that never reached ``sending`` provably sent nothing."""
REMINDER_UNFINISHED_AFTER: Final = timedelta(minutes=5)
REMINDER_RUNTIME_TTL: Final = timedelta(seconds=600)

# The message and the ledger (Rulings 25 and 28).
REMINDER_SUBJECT_MAX: Final = 200
LEDGER_DAYS: Final = 90
LEDGER_PRUNE_BATCH: Final = 1000
LEDGER_PRUNE_MAX_BATCHES: Final = 20
"""At most 20,000 ledger rows per tenant per janitor pass; the rest waits for the next hour."""
STATS_WINDOW_DAYS: Final = 30
