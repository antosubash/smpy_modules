"""Presets: what a host plugin bundles for a collection (spec §3, §8.3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CrossCheck", "Preset", "PromptSpec"]

# GroupRead / PromptResultRead arrive with the prompt tasks; until then a
# cross-check is typed over plain objects.
CrossCheck = Callable[[Any, list[Any]], dict[str, Any]]


class PromptSpec(BaseModel):
    id: str
    instruction: str
    output_schema: dict[str, Any] = Field(default_factory=dict)
    scope: Literal["image", "group"] = "image"
    auto_run: bool = False


class Preset(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    label_key: str
    pipeline: dict[str, dict[str, Any]] = Field(default_factory=dict)
    group_roles: list[str] = Field(default_factory=list)
    filename_patterns: list[str] = Field(default_factory=list)
    prompts: list[PromptSpec] = Field(default_factory=list)
    cross_check: CrossCheck | None = None
