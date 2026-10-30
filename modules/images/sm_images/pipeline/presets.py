"""Presets: what a host plugin bundles for a collection (spec §3, §8.3).

A :class:`Preset` is checked when it is built, so a malformed plugin fails at
boot: spec ids unique, names unique, a group prompt's ``member`` names an
image-scope spec of the same preset. ``register_preset`` also runs every
``output_schema`` through ``schema_safety``. Applying a preset to a collection
(:mod:`sm_images.web.services.presets`) is idempotent by :attr:`PromptSpec.id`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sm_images.pipeline.ai.reads import GroupRead, PromptResultRead

__all__ = ["CrossCheck", "Preset", "PromptSpec"]

CrossCheck = Callable[[GroupRead, list[PromptResultRead]], dict[str, Any]]
"""Pure: called after a group run with no session; see :mod:`sm_images.pipeline.ai.reads`."""

SPEC_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
Inputs = Literal["images", "results", "both"]
NEEDS_MEMBER = ("results", "both")


class PromptSpec(BaseModel):
    """One prompt a preset creates. ``name`` defaults to ``id``.

    A group prompt consolidates its members' ``images``, their ``results`` of
    the image-scope spec named by ``member``, or ``both``. ``member`` may be
    left out when the preset has exactly one image-scope spec.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=20000)
    output_schema: dict[str, Any] | None = None
    """A JSON Schema of the structured result; ``None`` = free text."""
    scope: Literal["image", "group"] = "image"
    inputs: Inputs | None = None
    member: str | None = None
    auto_run: bool = False

    @model_validator(mode="after")
    def _shape(self) -> PromptSpec:
        if not SPEC_ID.match(self.id):
            raise ValueError(f"prompt spec id {self.id!r} must be dotted [a-z][a-z0-9_]*")
        if self.scope == "image":
            if self.inputs is not None or self.member is not None:
                raise ValueError(f"{self.id}: inputs and member apply to group prompts only")
        elif self.auto_run:
            raise ValueError(f"{self.id}: a group prompt cannot auto-run")
        return self

    @property
    def label(self) -> str:
        return self.name or self.id

    def group_inputs(self) -> Inputs:
        return self.inputs or "images"


class Preset(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    label_key: str
    pipeline: dict[str, dict[str, Any]] = Field(default_factory=dict)
    group_roles: list[str] = Field(default_factory=list)
    filename_patterns: list[str] = Field(default_factory=list)
    prompts: list[PromptSpec] = Field(default_factory=list)
    cross_check: CrossCheck | None = None

    @model_validator(mode="after")
    def _prompts(self) -> Preset:
        ids = [p.id for p in self.prompts]
        names = [p.label for p in self.prompts]
        if len(set(ids)) != len(ids) or len(set(names)) != len(names):
            raise ValueError(f"preset {self.id!r}: prompt ids and names must be unique")
        images = [p.id for p in self.prompts if p.scope == "image"]
        resolved = []
        for spec in self.prompts:
            if spec.scope == "group" and spec.group_inputs() in NEEDS_MEMBER:
                member = spec.member
                if member is None and len(images) == 1:
                    member = images[0]
                if member not in images:
                    raise ValueError(
                        f"preset {self.id!r}: {spec.id} needs a member image prompt of the preset"
                    )
                spec = spec.model_copy(update={"member": member})
            elif spec.member is not None:
                raise ValueError(f"{spec.id}: member applies to inputs results or both only")
            resolved.append(spec)
        self.prompts = resolved
        return self
