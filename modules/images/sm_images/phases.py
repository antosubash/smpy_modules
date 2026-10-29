"""One tenant's pass of a platform beat as isolated phases.

``images.reconcile`` and ``images.janitor`` each run a list of independent
repairs per tenant. A phase that raises - one poison row, a store that is down
for a moment - is logged and counted as ``failed_phases``, and the phases after
it still run: one failure must not starve every later repair until it is fixed.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

__all__ = ["Phase", "run_phases"]

logger = logging.getLogger(__name__)

Phase = tuple[str, Callable[[], Awaitable[Any]]]
"""``(name, work)``: ``work()`` returns a count (recorded under ``name``), a
mapping of counts (merged), or ``None`` (nothing recorded)."""


async def run_phases(done: Counter[str], beat: str, tenant: str, phases: Iterable[Phase]) -> None:
    """Run ``phases`` in order into ``done``; a failure is logged and counted."""
    for name, work in phases:
        try:
            result = await work()
        except Exception:
            logger.exception("images.%s.phase_failed tenant=%s phase=%s", beat, tenant, name)
            done["failed_phases"] += 1
            continue
        if isinstance(result, Mapping):
            done.update(result)
        elif result is not None:
            done[name] = result
