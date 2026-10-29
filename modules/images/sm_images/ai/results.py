"""``images_prompt_result``: what a ``prompt:<id>`` run leaves for people to review.

Written by the run's completion, in its fenced transaction (under the image
lock), so a run whose lease was lost writes nothing:

* **completed** - the model output replaces the stored one, the run's prompt
  revision is recorded (an older one is *stale*), and the review resets to
  ``unreviewed``. A review that had been given is kept in ``history``
  (newest first, the last :data:`HISTORY_MAX`) with the output it judged;
  an entry over ``step_output_max_bytes`` keeps the verdict and drops the data.
* **failed** - ``status`` and ``error`` only: the previous output and its
  review stay, so a provider outage never erases accepted work.

A prompt deleted while its run was in flight writes nothing (its results went
with it).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from sm_images.ai.prompt_steps import prompt_id_of
from sm_images.models import Prompt, PromptResult
from sm_images.models.enums import ReviewStatus, StepStatus

__all__ = [
    "HISTORY_MAX",
    "PromptWrite",
    "encoded_size",
    "record_prompt_run",
    "reset_review",
    "upsert_result",
]

HISTORY_MAX = 5
ERROR_MAX = 2000
MODEL_MAX = 100


@dataclass(frozen=True)
class PromptWrite:
    prompt_id: uuid.UUID
    revision: int
    data: dict[str, Any] | None
    text: str | None
    model_name: str


def encoded_size(value: Any) -> int:
    """Bytes of ``value`` as the compact JSON it is stored as."""
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def _snapshot(row: PromptResult, max_bytes: int | None) -> dict[str, Any]:
    """A history entry; one over ``max_bytes`` keeps the verdict, not the data."""
    at = row.reviewed_at
    entry = {
        "review_status": row.review_status.value,
        "reviewed_data": row.reviewed_data,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": at.isoformat() if at is not None else None,
        "result_data": row.result_data,
        "result_text": row.result_text,
        "model_name": row.model_name,
        "prompt_revision": row.prompt_revision,
    }
    if max_bytes is not None and encoded_size(entry) > max_bytes:
        for key in ("reviewed_data", "result_data", "result_text"):
            entry[key] = None
        entry["truncated"] = True
    return entry


def reset_review(row: PromptResult, max_bytes: int | None = None) -> None:
    """Back to ``unreviewed``; a given review moves into ``history`` (each
    entry within ``max_bytes``)."""
    if row.review_status is not ReviewStatus.UNREVIEWED:
        row.history = [_snapshot(row, max_bytes), *(row.history or [])][:HISTORY_MAX]
    row.review_status = ReviewStatus.UNREVIEWED
    row.reviewed_data = None
    row.reviewed_by = None
    row.reviewed_at = None


async def _row(db: Any, prompt_id: uuid.UUID, image_id: uuid.UUID) -> PromptResult | None:
    stmt = select(PromptResult).where(
        PromptResult.prompt_id == prompt_id, PromptResult.image_id == image_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _prompt_exists(db: Any, prompt_id: uuid.UUID) -> bool:
    return (await db.execute(select(Prompt.id).where(Prompt.id == prompt_id))).first() is not None


async def upsert_result(
    db: Any, image_id: uuid.UUID, write: PromptWrite, *, max_bytes: int | None = None
) -> PromptResult:
    row = await _row(db, write.prompt_id, image_id)
    if row is None:
        row = PromptResult(prompt_id=write.prompt_id, image_id=image_id)
        db.add(row)
    else:
        reset_review(row, max_bytes)
    row.status = StepStatus.COMPLETED
    row.result_data = write.data
    row.result_text = write.text
    row.model_name = write.model_name[:MODEL_MAX] or None
    row.error = None
    row.prompt_revision = write.revision
    await db.flush()
    return row


async def _record_failure(
    db: Any, image_id: uuid.UUID, prompt_id: uuid.UUID, code: str, message: str | None
) -> None:
    row = await _row(db, prompt_id, image_id)
    if row is None:
        row = PromptResult(prompt_id=prompt_id, image_id=image_id)
        db.add(row)
    row.status = StepStatus.FAILED
    row.error = (f"{code}: {message}" if message else code)[:ERROR_MAX]
    await db.flush()


async def record_prompt_run(db: Any, loaded: Any, outcome: Any, staging: Any) -> None:
    """The completion's write for a ``prompt:*`` run (see the module docstring)."""
    prompt_id = prompt_id_of(loaded.step)
    if prompt_id is None or not await _prompt_exists(db, prompt_id):
        return
    write = getattr(staging, "prompt", None) if staging is not None else None
    if outcome.status == "completed" and isinstance(write, PromptWrite):
        limit = getattr(staging.settings, "step_output_max_bytes", None)
        await upsert_result(db, loaded.image_id, write, max_bytes=limit)
    elif outcome.status == "failed":
        await _record_failure(
            db, loaded.image_id, prompt_id, outcome.code or "failed", outcome.message
        )
