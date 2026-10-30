"""A group run's store phase: one fenced transaction on its result row.

Under :func:`~sm_images.pipeline.ai.group_lease.lock_group` and the row's own lock, the
outcome is written only if the lease is still ours and unexpired; otherwise
it is discarded, exactly as an image step's late completion is.

* A **summary** (``outcome.write``) replaces the output like an image result
  re-run does: the review goes back to ``unreviewed``, a given review moves to
  ``history``, the whole row is held to ``step_output_max_bytes``, and the
  cross-check is stored. With members missing, the summary is the best one
  available: it is stored, but the run is ``failed`` with the missing members
  named, so it is never taken for a complete verdict and the next run retries.
* **No summary** - ``failed`` with the code: the previous output, its review
  and its cross-check stay.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session

from sm_images.models.enums import StepStatus
from sm_images.pipeline.ai import group_lease
from sm_images.pipeline.ai.results import ERROR_MAX, PromptWrite, apply_write, reset_review

__all__ = ["GroupOutcome", "finish"]


@dataclass(frozen=True)
class GroupOutcome:
    write: PromptWrite | None = None
    cross_check: dict[str, Any] | None = None
    code: str | None = None
    """Set when the run failed (with or without a summary)."""
    message: str | None = None

    @classmethod
    def failed(cls, code: str, message: Any = None) -> GroupOutcome:
        return cls(code=code, message=None if message is None else str(message))

    @property
    def error(self) -> str | None:
        if self.code is None:
            return None
        return (f"{self.code}: {self.message}" if self.message else self.code)[:ERROR_MAX]


async def finish(
    runtime: Any,
    tenant: str,
    prompt_id: uuid.UUID,
    group_id: uuid.UUID,
    token: uuid.UUID,
    outcome: GroupOutcome,
) -> bool:
    """Record ``outcome`` if the lease is still ours; ``False`` = lost, discarded."""
    limit = runtime.settings().step_output_max_bytes
    async with runtime.session_factory() as db:
        await group_lease.lock_group(db, tenant, group_id)
        row = await group_lease.load(db, tenant, prompt_id, group_id)
        mine = group_lease.owned(row, token, datetime.now(UTC))
        if mine:
            if outcome.write is not None:
                reset_review(row, limit)
                apply_write(row, outcome.write, limit)
                row.cross_check = outcome.cross_check
            row.status = StepStatus.FAILED if outcome.code else StepStatus.COMPLETED
            row.error = outcome.error
            row.lease_token = None
            row.lease_expires_at = None
            row.ai_started_at = None
            await db.flush()
        await finalize_session(db)
    return mine
