"""``prompt:<id>`` steps: an image-scope prompt run per image (spec §3, §8.2).

The registry freezes implementations only, so prompt steps are resolved from
the database **per execution** (:func:`resolve`): one :class:`PromptStep` per
image-scope prompt of the collection, ``version`` = the prompt's
``revision``. Editing a prompt's instruction or schema bumps the revision, so
every run made under the old one is stale. Planning needs only ids and
revisions; the executor's load phase reads the instruction and schema of the
one prompt it runs (:func:`full`).

A prompt step runs when the collection's config enables ``prompt:<id>`` (every
image), or when a run is *requested* for an image - an ``auto_run`` prompt on
a new image (:func:`request_auto_run`, from ingest), or the run route
(:mod:`sm_images.pipeline.ai.run`). A requested run is a pending ``StepRun`` row the
planner honours whatever the config says.

Group-scope prompts are not steps (Task 23 runs them per group).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from sm_images.models import Prompt, StepRun
from sm_images.models.enums import PromptScope
from sm_images.pipeline import ai, registry
from sm_images.pipeline.step import StepContext, StepOutcome, failure

__all__ = ["PromptStep", "full", "prompt_id_of", "request_auto_run", "resolve", "step_id"]

MAX_SIDE = 1024


class PromptParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class PromptSpec:
    id: uuid.UUID
    revision: int
    instruction: str | None = None
    output_schema: dict[str, Any] | None = None


def step_id(prompt_id: uuid.UUID) -> str:
    return f"{registry.PROMPT_PREFIX}{prompt_id}"


def prompt_id_of(step: str) -> uuid.UUID | None:
    if not step.startswith(registry.PROMPT_PREFIX):
        return None
    try:
        return uuid.UUID(step.removeprefix(registry.PROMPT_PREFIX))
    except ValueError:
        return None


class PromptStep:
    requires: tuple[str, ...] = ()
    """The planner adds the enabled display mutator: the picture sent is redacted."""
    mutates_display = False
    sends_display_out = True
    queue = "images_heavy"

    def __init__(self, spec: PromptSpec) -> None:
        self.spec = spec
        self.id = step_id(spec.id)
        self.version = spec.revision

    def params_schema(self) -> type[BaseModel]:
        return PromptParams

    def applies(self, image: Any, params: BaseModel) -> bool:
        return True

    async def run(self, ctx: StepContext) -> StepOutcome:
        from sm_images.pipeline.ai.results import PromptWrite, write_size
        from sm_images.pipeline.ai.runner import ai_call
        from sm_images.pipeline.ai.schema_safety import UnsafeSchema, output_model

        spec = self.spec
        if spec.instruction is None:
            raise RuntimeError(f"{self.id}: run a prompt step loaded with full()")
        schema = spec.output_schema
        try:  # stored before a cap existed, or edited in the database: refused here too
            out_type: Any = (
                str if schema is None else output_model(schema, key=(spec.id, spec.revision))
            )
        except UnsafeSchema as exc:
            return StepOutcome.failed("unsafe_output_schema", str(exc))
        result = await ai_call(
            ctx,
            spec.instruction,
            out_type,
            version=self.version,
            max_side=MAX_SIDE,
            source="images:prompt",
        )
        if isinstance(result, StepOutcome):
            return result
        data, model_name = result
        write = PromptWrite(
            prompt_id=spec.id,
            revision=spec.revision,
            data=data if isinstance(data, dict) else None,
            text=data if isinstance(data, str) else None,
            model_name=model_name,
        )
        limit = ctx._staging.settings.step_output_max_bytes
        size = write_size(write)
        if size > limit:  # the stored result obeys the cap step outputs do
            return failure("output_too_large", f"the result is {size} bytes; the limit is {limit}")
        ctx._staging.prompt = write
        return StepOutcome.completed({"model": model_name, "structured": schema is not None})


def _where(collection_id: uuid.UUID, tenant: str) -> list[Any]:
    return [
        Prompt.collection_id == collection_id,
        Prompt.tenant_id == tenant,
        Prompt.scope == PromptScope.IMAGE,
    ]


async def resolve(db: Any, collection: Any, *, tenant: str | None = None) -> list[PromptStep]:
    """The collection's image-scope prompt steps (ids and revisions only).
    ``collection`` is a row or its id; ``[]`` without the ``[ai]`` extra."""
    if not ai.ai_available():
        return []
    collection_id = getattr(collection, "id", collection)
    if tenant is None:
        from sm_images.core.tenancy import bound_tenant

        tenant = getattr(collection, "tenant_id", None) or bound_tenant()
    stmt = select(Prompt.id, Prompt.revision).where(*_where(collection_id, tenant))
    return [PromptStep(PromptSpec(pid, rev)) for pid, rev in (await db.execute(stmt)).all()]


async def full(db: Any, tenant: str, step: PromptStep) -> PromptStep | None:
    """``step`` with its instruction and schema, at the revision now stored."""
    stmt = select(Prompt.revision, Prompt.instruction, Prompt.output_schema).where(
        Prompt.id == step.spec.id, Prompt.tenant_id == tenant
    )
    row = (await db.execute(stmt)).first()
    return None if row is None else PromptStep(PromptSpec(step.spec.id, *row))


async def request_auto_run(db: Any, collection: Any, image_id: uuid.UUID) -> list[str]:
    """Pending runs of the collection's ``auto_run`` image prompts for a new
    image, in ``db``'s transaction; the image's dispatch plans them."""
    if not ai.ai_available():
        return []
    from sm_images.pipeline import enabled_steps

    stmt = select(Prompt.id).where(
        *_where(collection.id, collection.tenant_id), Prompt.auto_run.is_(True)
    )
    enabled = set(enabled_steps(collection.pipeline_config))
    ids = [step_id(pid) for pid in (await db.execute(stmt)).scalars()]
    ids = [sid for sid in ids if sid not in enabled]  # ingest already inserted those
    for sid in ids:
        db.add(StepRun(image_id=image_id, step=sid))
    if ids:
        await db.flush()
    return ids
