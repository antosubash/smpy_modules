"""Call a preset's cross-check: pure, no session, its failure captured.

The hook (spec §8.3) is plugin code run inside the group-run task. Whatever it
does wrong becomes the stored value ``{"error": "..."}`` and never fails the
group run (and it gets deep copies, so mutating its arguments changes nothing
that is stored): an exception, a value that is not a dict, one that is not strict
JSON, or one over ``step_output_max_bytes`` once encoded - the cap every step
output and prompt result obeys.

It runs in a worker thread (:func:`check`), so a slow hook never blocks the
event loop - the lease keeps renewing - and under :data:`CROSS_CHECK_TIMEOUT_S`.
A hook past it is :class:`CrossCheckTimedOut`, which fails the group run
``time_limit``: it is left running in its thread (Python cannot stop one), but
nothing waits for it and its value is never stored.

The thread is one of :data:`_POOL`'s, not the loop's default executor: a task
body runs under ``asyncio.run`` (``worker_runtime.run_task``), whose shutdown
joins every default-executor thread, so an abandoned hook there would hold the
Celery task until it returned. A hung hook keeps its pool thread until it
returns, so at most :data:`POOL_SIZE` hang at once; while all of them do,
further cross-checks queue behind them and time out.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sm_images.ai.reads import GroupRead, PromptResultRead

__all__ = ["CROSS_CHECK_TIMEOUT_S", "ERROR_MAX", "CrossCheckTimedOut", "check", "run_cross_check"]

logger = logging.getLogger(__name__)
ERROR_MAX = 1000
CROSS_CHECK_TIMEOUT_S = 30.0
"""How long a group run waits for its preset's cross-check."""
POOL_SIZE = 4
_POOL = ThreadPoolExecutor(max_workers=POOL_SIZE, thread_name_prefix="images-cross-check")


class CrossCheckTimedOut(Exception):  # noqa: N818 - reads as the condition
    """The hook did not return within :data:`CROSS_CHECK_TIMEOUT_S`."""


def _error(message: str) -> dict[str, Any]:
    return {"error": message[:ERROR_MAX]}


def run_cross_check(
    fn: Any, group: GroupRead, results: Sequence[PromptResultRead], max_bytes: int
) -> dict[str, Any] | None:
    """``fn(group, results)`` bounded as above; ``None`` without a hook."""
    if fn is None:
        return None
    try:  # copies: the hook must never reach the summary about to be stored
        out = fn(group.model_copy(deep=True), [r.model_copy(deep=True) for r in results])
    except Exception as exc:  # plugin code: captured, never the run's failure
        logger.warning("images.group.cross_check_raised", exc_info=True)
        return _error(f"{type(exc).__name__}: {exc}")
    if not isinstance(out, dict):
        return _error(f"cross_check returned {type(out).__name__}, not a dict")
    try:
        encoded = json.dumps(out, allow_nan=False, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return _error(f"cross_check returned a value that is not JSON: {exc}")
    size = len(encoded.encode())
    if size > max_bytes:
        return _error(f"cross_check_too_large: {size} bytes; the limit is {max_bytes}")
    return json.loads(encoded)


async def check(
    fn: Any, group: GroupRead, results: Sequence[PromptResultRead], max_bytes: int
) -> dict[str, Any] | None:
    """:func:`run_cross_check` off the event loop, bounded by the timeout."""
    if fn is None:
        return None
    limit = CROSS_CHECK_TIMEOUT_S
    call = functools.partial(run_cross_check, fn, group, results, max_bytes)
    ctx = contextvars.copy_context()  # as ``asyncio.to_thread`` would
    work = asyncio.get_running_loop().run_in_executor(_POOL, ctx.run, call)
    try:
        return await asyncio.wait_for(work, limit)
    except TimeoutError as exc:
        raise CrossCheckTimedOut(f"the cross-check took longer than {limit:g} s") from exc
