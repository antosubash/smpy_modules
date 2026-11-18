"""The public surface's "now", in one place a test can replace."""

from __future__ import annotations

from datetime import datetime

from sm_events.core.clock import utcnow

__all__ = ["now"]


def now() -> datetime:
    return utcnow()
