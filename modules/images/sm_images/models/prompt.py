"""Custom prompts (the portal's custom pipelines, generalised) and their results."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, enum_col, fk_uuid, json_col, json_null, pk_uuid
from sm_images.models.enums import PromptScope, ReviewStatus, StepStatus


class Prompt(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_prompt"

    id: uuid.UUID = pk_uuid()
    collection_id: uuid.UUID = fk_uuid("images_collection.id")
    name: str = Field(max_length=200)
    scope: PromptScope = enum_col(PromptScope, "prompt_scope", PromptScope.IMAGE)
    instruction: str = Field(max_length=20000)
    output_schema: dict[str, Any] | None = json_null()
    """JSON Schema of the structured result; ``None`` = free text."""
    inputs: str | None = Field(default=None, max_length=20)
    auto_run: bool = Field(default=False)
    preset_id: str | None = Field(default=None, max_length=100)
    revision: int = Field(default=1, sa_column_kwargs={"nullable": False})
    """Bumped when the instruction or schema is edited; a result produced under
    an older revision is stale."""


class PromptResult(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_prompt_result"
    __table_args__ = (
        UniqueConstraint("prompt_id", "image_id", name="uq_images_prompt_result_image"),
        UniqueConstraint("prompt_id", "group_id", name="uq_images_prompt_result_group"),
    )

    id: int | None = Field(default=None, primary_key=True)
    prompt_id: uuid.UUID = fk_uuid("images_prompt.id", ondelete="CASCADE")
    image_id: uuid.UUID | None = fk_uuid("images_image.id", nullable=True, ondelete="CASCADE")
    group_id: uuid.UUID | None = fk_uuid("images_group.id", nullable=True, ondelete="CASCADE")
    status: StepStatus = enum_col(StepStatus, "result_status", StepStatus.PENDING)
    result_text: str | None = Field(default=None)
    result_data: dict[str, Any] | None = json_null()
    model_name: str | None = Field(default=None, max_length=100)
    error: str | None = Field(default=None, max_length=2000)
    cross_check: dict[str, Any] | None = json_null()
    review_status: ReviewStatus = enum_col(ReviewStatus, "review_status", ReviewStatus.UNREVIEWED)
    reviewed_data: dict[str, Any] | None = json_null()
    reviewed_by: str | None = Field(default=None, max_length=255)
    reviewed_at: datetime | None = dt_col()
    history: list[dict[str, Any]] = json_col(list)
    """The last 5 reviewed values, newest first, kept when a re-run resets the review."""
