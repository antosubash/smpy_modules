"""Prompt request bodies (bounded) and responses.

``inputs`` says what a group-scope prompt consolidates - the members'
``images``, their image-scope ``results``, or ``both`` - and means nothing for
an image-scope prompt, so it is refused there and defaults to ``images`` for
a group. The check runs on the *merged* prompt for an update
(:func:`check_inputs`). ``scope`` is fixed at creation: an image prompt's
results are per image, a group prompt's per group.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from sm_images.ai.run import IDS_MAX
from sm_images.models.enums import PromptScope, ReviewStatus, StepStatus

Inputs = Literal["images", "results", "both"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Instruction = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)
]
DEFAULT_GROUP_INPUTS: Inputs = "images"


def check_inputs(scope: PromptScope, inputs: str | None) -> str | None:
    """``inputs`` for ``scope``; ``ValueError`` when it does not apply."""
    if scope is PromptScope.IMAGE:
        if inputs is not None:
            raise ValueError("inputs applies to group-scope prompts only")
        return None
    return inputs or DEFAULT_GROUP_INPUTS


class PromptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    scope: PromptScope = PromptScope.IMAGE
    instruction: Instruction
    output_schema: dict[str, Any] | None = None
    """A JSON Schema (checked by ``schema_safety``); ``null`` = free text."""
    inputs: Inputs | None = None
    auto_run: bool = False

    @model_validator(mode="after")
    def _inputs(self) -> PromptCreate:
        self.inputs = check_inputs(self.scope, self.inputs)  # type: ignore[assignment]
        return self


class PromptUpdate(BaseModel):
    """Only the fields sent change. A new ``instruction`` or ``output_schema``
    bumps the revision, which makes every result made before it stale."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    instruction: Instruction | None = None
    output_schema: dict[str, Any] | None = None
    inputs: Inputs | None = None
    auto_run: bool | None = None


class PromptOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    name: str
    scope: PromptScope
    instruction: str
    output_schema: dict[str, Any] | None
    inputs: str | None
    auto_run: bool
    preset_id: str | None
    revision: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PromptListOut(BaseModel):
    items: list[PromptOut]


class PromptRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["missing", "stale", "all"] = "missing"
    image_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=IDS_MAX)
    """Only these images of the prompt's collection; all of them when absent."""


class PromptRunOut(BaseModel):
    status: Literal["accepted"] = "accepted"
    scope: str
    requested: int | None
    """Images given a new run; ``null`` when the walk was queued."""


class PromptResultOut(BaseModel):
    id: int
    prompt_id: uuid.UUID
    image_id: uuid.UUID | None
    group_id: uuid.UUID | None
    status: StepStatus
    result_text: str | None
    result_data: dict[str, Any] | None
    model_name: str | None
    error: str | None
    prompt_revision: int | None
    stale: bool
    """Produced under an older revision of the prompt."""
    review_status: ReviewStatus
    reviewed_data: dict[str, Any] | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    history: list[dict[str, Any]]
    updated_at: datetime | None = None


class PromptResultPageOut(BaseModel):
    items: list[PromptResultOut]
    next_cursor: int | None
