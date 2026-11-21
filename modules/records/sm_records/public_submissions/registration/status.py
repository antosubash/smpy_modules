"""The statuses of a registration record (``sm_status``), spelled once.

A **pending** registration is unconfirmed and holds no seat (double opt-in); a **registered** one
holds its seat; a **cancelled** one is kept for the organiser and holds nothing. ``LIVE`` are the
two a person can still act on; ``SEATED`` is the only one that owns a seat.
"""

from __future__ import annotations

from typing import Final

__all__ = ["CANCELLED", "LIVE", "PENDING", "REGISTERED", "SEATED"]

PENDING: Final = "pending"
REGISTERED: Final = "registered"
CANCELLED: Final = "cancelled"
LIVE: Final = (PENDING, REGISTERED)
SEATED: Final = (REGISTERED,)
