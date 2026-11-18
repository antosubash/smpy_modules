"""What other modules may import from events: its bus events
(:mod:`sm_events.contracts.events`), the bounded occurrences read
(:mod:`sm_events.contracts.occurrences`) and :func:`mounted`."""

from __future__ import annotations

from typing import Any

from sm_events.core import constants

__all__ = ["mounted"]


def mounted(app: Any) -> bool:
    """Whether the events module is mounted on ``app`` (installed is not enough),
    so a caller never reads ``app.state.sm_events`` itself."""
    return getattr(getattr(app, "state", None), constants.PACKAGE, None) is not None
