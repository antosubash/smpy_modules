"""Prompt CRUD and the result list (the routes are thin over these).

The caller's session, nothing committed here. Every query names the
collection, and the collection was loaded through the access policy, so a
prompt is reachable exactly when its collection is.

* A prompt's ``output_schema`` passes ``schema_safety.check`` before it is
  stored (422 ``unsafe_output_schema``), on create and on every update.
* Editing the ``instruction`` or ``output_schema`` bumps ``revision``: results
  made before it are stale, and the next run's version differs.
* Names are unique per collection (409 ``prompt_name_taken``).
* Deleting a prompt deletes its results and its runs: an in-flight run then
  finds no row to complete and its result is discarded.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select

from sm_images import constants
from sm_images.ai import prompt_steps
from sm_images.ai.schema_safety import UnsafeSchema, check
from sm_images.errors import Conflict, Invalid, NotFound
from sm_images.models import Collection, Image, Prompt, PromptResult, StepRun
from sm_images.schemas.prompt import PromptCreate, check_inputs

__all__ = ["create", "delete_prompt", "get", "list_prompts", "results_page", "update"]

REVISING = frozenset({"instruction", "output_schema"})


def _invalid(detail: str, code: str) -> Invalid:
    err = Invalid(detail[:1000])
    err.code = code
    return err


def _check_schema(schema: Any) -> None:
    if schema is None:
        return
    try:
        check(schema)
    except UnsafeSchema as exc:
        raise _invalid(str(exc), constants.CODE_UNSAFE_SCHEMA) from exc


async def _name_free(db: Any, collection: Collection, name: str, but: uuid.UUID | None) -> None:
    stmt = select(Prompt.id).where(Prompt.collection_id == collection.id, Prompt.name == name)
    if but is not None:
        stmt = stmt.where(Prompt.id != but)
    if (await db.execute(stmt)).first() is not None:
        err = Conflict("a prompt with this name already exists in the collection")
        err.code = constants.CODE_PROMPT_NAME_TAKEN
        raise err


async def list_prompts(db: Any, collection: Collection) -> list[Prompt]:
    stmt = select(Prompt).where(Prompt.collection_id == collection.id).order_by(Prompt.name)
    return list((await db.execute(stmt)).scalars())


async def get(db: Any, collection: Collection, prompt_id: uuid.UUID) -> Prompt:
    stmt = select(Prompt).where(Prompt.id == prompt_id, Prompt.collection_id == collection.id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFound("prompt not found")
    return row


async def create(db: Any, collection: Collection, body: PromptCreate) -> Prompt:
    _check_schema(body.output_schema)
    await _name_free(db, collection, body.name, None)
    row = Prompt(collection_id=collection.id, **body.model_dump())
    db.add(row)
    await db.flush()
    return row


REQUIRED = ("name", "instruction", "auto_run")
"""Columns a ``null`` in an update leaves unchanged (they cannot be cleared)."""


async def update(db: Any, collection: Collection, row: Prompt, changes: dict[str, Any]) -> Prompt:
    changes = {k: v for k, v in changes.items() if not (k in REQUIRED and v is None)}
    if "output_schema" in changes:
        _check_schema(changes["output_schema"])
    if "name" in changes:
        await _name_free(db, collection, changes["name"], row.id)
    try:
        inputs = check_inputs(row.scope, changes.get("inputs", row.inputs))
    except ValueError as exc:
        raise _invalid(str(exc), constants.CODE_INVALID_INPUTS) from exc
    revised = any(k in changes and changes[k] != getattr(row, k) for k in REVISING)
    for key, value in changes.items():
        setattr(row, key, value)
    row.inputs = inputs
    if revised:
        row.revision += 1
    await db.flush()
    return row


async def delete_prompt(db: Any, collection: Collection, row: Prompt) -> None:
    images = select(Image.id).where(Image.collection_id == collection.id)
    sid = prompt_steps.step_id(row.id)
    sync = {"synchronize_session": False}
    await db.execute(
        delete(StepRun)
        .where(StepRun.step == sid, StepRun.image_id.in_(images))
        .execution_options(**sync)
    )
    await db.execute(
        delete(PromptResult).where(PromptResult.prompt_id == row.id).execution_options(**sync)
    )
    await db.delete(row)
    await db.flush()


async def results_page(
    db: Any, row: Prompt, *, limit: int, after: int | None
) -> tuple[list[PromptResult], int | None]:
    """Results of untrashed images (and groups), by id."""
    stmt = (
        select(PromptResult)
        .outerjoin(Image, Image.id == PromptResult.image_id)
        .where(PromptResult.prompt_id == row.id)
        .where((PromptResult.image_id.is_(None)) | (Image.is_deleted.is_(False)))
        .order_by(PromptResult.id)
        .limit(limit + 1)
    )
    if after is not None:
        stmt = stmt.where(PromptResult.id > after)
    rows = list((await db.execute(stmt)).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, (rows[-1].id if more and rows else None)
