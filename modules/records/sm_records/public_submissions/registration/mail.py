"""The registration mail (PR 9). Filled in with the confirmation and cancel links (Task 10)."""

from __future__ import annotations

from typing import Any

__all__ = ["queue_registration_mail"]


async def queue_registration_mail(
    db: Any, request: Any, rtype: Any, record: Any, event: Any
) -> None:
    """Send ``record`` its registration mail once ``db`` commits (not yet implemented)."""
    return
