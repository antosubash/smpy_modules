"""One tenant's pass of a platform beat as isolated phases.

``images.reconcile`` and ``images.janitor`` each run a list of independent
repairs per tenant. A phase that raises - one poison row, a store that is down
for a moment - is logged and counted as ``failed_phases``, and the phases after
it still run: one failure must not starve every later repair until it is fixed.

A phase that is only safe after another one may name it as a third element,
``(name, work, after)``: it runs only if ``after`` succeeded earlier in this
pass, and is otherwise logged and counted as ``skipped_phases`` (reconcile's
image dispatch must not run while unleased rows are still unrepaired).
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

__all__ = ["Phase", "run_phases"]

logger = logging.getLogger(__name__)

Work = Callable[[], Awaitable[Any]]
Phase = tuple[str, Work] | tuple[str, Work, str]
"""``(name, work)`` or ``(name, work, after)``: ``work()`` returns a count
(recorded under ``name``), a mapping of counts (merged), or ``None`` (nothing
recorded); ``after`` names the phase that must have succeeded first."""


async def run_phases(done: Counter[str], beat: str, tenant: str, phases: Iterable[Phase]) -> None:
    """Run ``phases`` in order into ``done``; a failure is logged and counted."""
    succeeded: set[str] = set()
    for name, work, *after in phases:
        if after and after[0] not in succeeded:
            logger.warning(
                "images.%s.phase_skipped tenant=%s phase=%s after=%s", beat, tenant, name, after[0]
            )
            done["skipped_phases"] += 1
            continue
        try:
            result = await work()
        except Exception:
            logger.exception("images.%s.phase_failed tenant=%s phase=%s", beat, tenant, name)
            done["failed_phases"] += 1
            continue
        succeeded.add(name)
        if isinstance(result, Mapping):
            done.update(result)
        elif result is not None:
            done[name] = result
