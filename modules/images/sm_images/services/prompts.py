"""Prompt CRUD and the result list (the routes are thin over these).

The caller's session, nothing committed here. Every query names the
collection, and the collection was loaded through the access policy, so a
prompt is reachable exactly when its collection is.

* A prompt's ``output_schema`` passes ``schema_safety.check`` before it is
  stored (422 ``unsafe_output_schema``), on create and on every update.
* Editing the ``instruction``, ``output_schema``, ``inputs`` or member prompt
  bumps ``revision``: results made before it are stale, and the next run's
  version differs.
* Names are unique per collection (409 ``prompt_name_taken``): checked here
  for the common case and enforced by ``uq_images_prompt_name``, whose
  violation by a concurrent create or rename is the same 409.
* A group prompt with ``inputs`` ``results``/``both`` names the collection's
  image-scope prompt it consolidates (``member_prompt_id``); anything else
  names none (422 ``invalid_prompt_inputs``). A prompt so named cannot be
  deleted (409 ``prompt_in_use``).
* Deleting a prompt deletes its results and its runs: an in-flight run then
  finds no row to complete and its result is discarded.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from sm_images.ai import codes, prompt_steps
from sm_images.ai.schema_safety import UnsafeSchema, check
from sm_images.errors import Conflict, Invalid, NotFound
from sm_images.models import Collection, Image, Prompt, PromptResult, StepRun
from sm_images.models.enums import PromptScope
from sm_images.schemas.prompt import PromptCreate, check_inputs

__all__ = [
    "check_schema",
    "create",
    "delete_prompt",
    "get",
    "list_prompts",
    "name_taken",
    "results_page",
    "saved",
    "update",
]

REVISING = frozenset({"instruction", "output_schema", "inputs", "member_prompt_id"})
NEEDS_MEMBER = ("results", "both")


def _invalid(detail: str, code: str) -> Invalid:
    err = Invalid(detail[:1000])
    err.code = code
    return err


def name_taken() -> Conflict:
    err = Conflict("a prompt with this name already exists in the collection")
    err.code = codes.CODE_PROMPT_NAME_TAKEN
    return err


def check_schema(schema: Any) -> None:
    if schema is None:
        return
    try:
        check(schema)
    except UnsafeSchema as exc:
        raise _invalid(str(exc), codes.CODE_UNSAFE_SCHEMA) from exc


async def _name_free(db: Any, collection: Collection, name: str, but: uuid.UUID | None) -> None:
    stmt = select(Prompt.id).where(Prompt.collection_id == collection.id, Prompt.name == name)
    if but is not None:
        stmt = stmt.where(Prompt.id != but)
    if (await db.execute(stmt)).first() is not None:
        raise name_taken()


async def saved(db: Any) -> None:
    """Flush in a savepoint; the name constraint's violation is the 409."""
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise name_taken() from None


async def list_prompts(db: Any, collection: Collection) -> list[Prompt]:
    stmt = select(Prompt).where(Prompt.collection_id == collection.id).order_by(Prompt.name)
    return list((await db.execute(stmt)).scalars())


async def get(db: Any, collection: Collection, prompt_id: uuid.UUID) -> Prompt:
    stmt = select(Prompt).where(Prompt.id == prompt_id, Prompt.collection_id == collection.id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFound("prompt not found")
    return row


def _inputs(scope: Any, inputs: str | None) -> str | None:
    try:
        return check_inputs(scope, inputs)
    except ValueError as exc:
        raise _invalid(str(exc), codes.CODE_INVALID_INPUTS) from exc


async def _check_member(
    db: Any, collection: Collection, scope: Any, inputs: str | None, member: uuid.UUID | None
) -> None:
    if scope is not PromptScope.GROUP or inputs not in NEEDS_MEMBER:
        if member is not None:
            raise _invalid(
                "member_prompt_id applies to a group prompt over results",
                codes.CODE_INVALID_INPUTS,
            )
        return
    stmt = select(Prompt.id).where(
        Prompt.id == member,
        Prompt.collection_id == collection.id,
        Prompt.scope == PromptScope.IMAGE,
    )
    if member is None or (await db.execute(stmt)).first() is None:
        raise _invalid(
            "a group prompt over results names an image prompt of the collection",
            codes.CODE_INVALID_INPUTS,
        )


async def create(db: Any, collection: Collection, body: PromptCreate, **extra: Any) -> Prompt:
    """``extra`` - columns a preset sets (``preset_id``, ``preset_prompt_id``)."""
    check_schema(body.output_schema)
    inputs = _inputs(body.scope, body.inputs)
    await _check_member(db, collection, body.scope, inputs, body.member_prompt_id)
    await _name_free(db, collection, body.name, None)
    row = Prompt(collection_id=collection.id, **{**body.model_dump(), "inputs": inputs, **extra})
    db.add(row)
    await saved(db)
    return row


REQUIRED = ("name", "instruction", "auto_run")
"""Columns a ``null`` in an update leaves unchanged (they cannot be cleared)."""


async def update(db: Any, collection: Collection, row: Prompt, changes: dict[str, Any]) -> Prompt:
    changes = {k: v for k, v in changes.items() if not (k in REQUIRED and v is None)}
    if "output_schema" in changes:
        check_schema(changes["output_schema"])
    if "name" in changes:
        await _name_free(db, collection, changes["name"], row.id)
    inputs = _inputs(row.scope, changes.get("inputs", row.inputs))
    member = changes.get("member_prompt_id", row.member_prompt_id)
    await _check_member(db, collection, row.scope, inputs, member)
    changes["inputs"] = inputs
    revised = any(k in changes and changes[k] != getattr(row, k) for k in REVISING)
    for key, value in changes.items():
        setattr(row, key, value)
    if revised:
        row.revision += 1
    await saved(db)
    return row


async def delete_prompt(db: Any, collection: Collection, row: Prompt) -> None:
    users = select(Prompt.name).where(
        Prompt.collection_id == collection.id, Prompt.member_prompt_id == row.id
    )
    if (await db.execute(users)).first() is not None:
        err = Conflict("a group prompt consolidates this prompt's results; change it first")
        err.code = codes.CODE_PROMPT_IN_USE
        raise err
    # By step id alone: the id names this prompt, and a trashed image's runs
    # (which an image subquery would filter out) must go too.
    sid = prompt_steps.step_id(row.id)
    sync = {"synchronize_session": False}
    await db.execute(delete(StepRun).where(StepRun.step == sid).execution_options(**sync))
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
