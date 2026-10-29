"""Call a preset's cross-check: pure, no session, its failure captured.

The hook (spec §8.3) is plugin code run inside the group-run task. Whatever it
does wrong becomes the stored value ``{"error": "..."}`` and never fails the
group run: an exception, a value that is not a dict, one that is not strict
JSON, or one over ``step_output_max_bytes`` once encoded - the cap every step
output and prompt result obeys.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from sm_images.ai.reads import GroupRead, PromptResultRead

__all__ = ["ERROR_MAX", "run_cross_check"]

logger = logging.getLogger(__name__)
ERROR_MAX = 1000


def _error(message: str) -> dict[str, Any]:
    return {"error": message[:ERROR_MAX]}


def run_cross_check(
    fn: Any, group: GroupRead, results: Sequence[PromptResultRead], max_bytes: int
) -> dict[str, Any] | None:
    """``fn(group, results)`` bounded as above; ``None`` without a hook."""
    if fn is None:
        return None
    try:
        out = fn(group, list(results))
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
