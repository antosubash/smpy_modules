"""Reviewing a prompt result: accept, correct or reject (spec §6).

A review and a re-run both write the same row, so a review runs under the
owning image's (or group's) lock - the lock a run's completion takes - and
applies only if the row still has the ``version`` the reviewer saw. That
version covers the output, its prompt revision and the review itself, so a
review of output A never lands on a re-run's output B (409 ``review_stale``;
the client reloads).

* ``accept`` - the model output becomes the reviewed value.
* ``correct`` - ``data`` is validated through the model :func:`build_model`
  builds from the prompt's ``output_schema`` (422 ``invalid_review_data``);
  a free-text prompt is corrected with ``{"text": "..."}``.
* ``reject`` - no reviewed data.

A review that had been given moves into ``history`` first (the rule a re-run
follows, :func:`sm_images.pipeline.ai.results.reset_review`).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from sm_images.core.errors import Conflict, Invalid, NotFound
from sm_images.models import Prompt, PromptResult
from sm_images.models.enums import ReviewStatus, StepStatus
from sm_images.pipeline.ai import codes
from sm_images.pipeline.ai.group_lease import lock_group
from sm_images.pipeline.ai.results import encoded_size, reset_review
from sm_images.pipeline.ai.schema_model import build_model
from sm_images.pipeline.claim import lock_image

__all__ = ["ACTIONS", "apply", "version_of"]

ACTIONS = ("accept", "correct", "reject")
_STATUS = {
    "accept": ReviewStatus.ACCEPTED,
    "correct": ReviewStatus.CORRECTED,
    "reject": ReviewStatus.REJECTED,
}


def version_of(row: PromptResult) -> str:
    """What a reviewer saw of ``row``: change any of it and a review is stale."""
    at = row.reviewed_at
    seen = [
        row.status.value,
        row.prompt_revision,
        row.result_data,
        row.result_text,
        row.model_name,
        row.review_status.value,
        at.isoformat() if at else None,
    ]
    blob = json.dumps(seen, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _invalid(detail: str, code: str = codes.CODE_INVALID_REVIEW) -> Invalid:
    return Invalid(detail[:1000], code=code)


def _where(error: Any) -> str:
    return ".".join(map(str, error["loc"]))


def _corrected(prompt: Prompt, data: dict[str, Any] | None) -> dict[str, Any]:
    if data is None:
        raise _invalid("a correction needs data")
    schema = prompt.output_schema
    if schema is None:
        if set(data) != {"text"} or not isinstance(data["text"], str):
            raise _invalid('a free-text result is corrected with {"text": "..."}')
        return data
    try:
        model: type[BaseModel] = build_model(schema)
        checked = model.model_validate(data, strict=True)
    except ValidationError as exc:
        raise _invalid("; ".join(f"{_where(e)}: {e['msg']}" for e in exc.errors())) from exc
    except Exception as exc:  # a schema the builder cannot realise
        raise _invalid(str(exc), codes.CODE_INVALID_SCHEMA) from exc
    return checked.model_dump(mode="json", by_alias=True, exclude_unset=True)


async def _lock(db: Any, tenant: str, row: PromptResult) -> None:
    if row.image_id is not None:
        found = await lock_image(db, tenant, row.image_id) is not None
    else:
        found = row.group_id is not None and await lock_group(db, tenant, row.group_id)
    if not found:
        raise NotFound("result not found")


async def apply(
    db: Any,
    tenant: str,
    result_id: int,
    collection_id: uuid.UUID,
    *,
    action: str,
    data: dict[str, Any] | None,
    version: str,
    reviewer: str,
    max_bytes: int | None,
) -> tuple[PromptResult, Prompt]:
    """Review result ``result_id`` of the collection; the caller commits."""
    head = select(PromptResult, Prompt).join(Prompt, Prompt.id == PromptResult.prompt_id)
    found = (
        await db.execute(
            head.where(PromptResult.id == result_id, Prompt.collection_id == collection_id)
        )
    ).first()
    if found is None:
        raise NotFound("result not found")
    await _lock(db, tenant, found[0])
    # Read again under the lock: a run that finished while we waited is seen.
    locked = (
        await db.execute(
            select(PromptResult)
            .where(PromptResult.id == result_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    prompt = found[1]
    if locked is None:
        raise NotFound("result not found")
    if locked.status is not StepStatus.COMPLETED or version_of(locked) != version:
        raise Conflict("the result changed since it was loaded", code=codes.CODE_REVIEW_STALE)
    reviewed = _corrected(prompt, data) if action == "correct" else None
    if reviewed is not None and max_bytes is not None and encoded_size(reviewed) > max_bytes:
        raise _invalid("the correction is too large")
    if action == "accept":  # the model's answer, structured or free text
        reviewed = locked.result_data
        if reviewed is None and locked.result_text is not None:
            reviewed = {"text": locked.result_text}
    reset_review(locked, max_bytes)  # a given review moves into history
    locked.review_status = _STATUS[action]
    locked.reviewed_data = reviewed
    locked.reviewed_by = reviewer
    locked.reviewed_at = datetime.now(UTC)
    await db.flush()
    return locked, prompt
