"""Request bodies of the pipeline API."""

from __future__ import annotations

from typing import Any, Literal

from sqlmodel import SQLModel


class PipelineConfigIn(SQLModel):
    """``PUT .../pipeline``: ``{"steps": {id: {"enabled": bool, ...params}}}``."""

    model_config = {"extra": "forbid"}

    steps: dict[str, dict[str, Any]]


class RestartIn(SQLModel):
    """``failed``: failed and blocked runs; ``stale``: results of an older step
    version; ``all``: everything not running."""

    model_config = {"extra": "forbid"}

    scope: Literal["failed", "stale", "all"]


class ReprocessIn(SQLModel):
    model_config = {"extra": "forbid"}

    force: bool = False
