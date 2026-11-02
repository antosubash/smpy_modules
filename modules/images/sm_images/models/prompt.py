"""Custom prompts (the portal's custom pipelines, generalised) and their results."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import Column, UniqueConstraint, Uuid
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, enum_col, fk_uuid, json_col, json_null, pk_uuid
from sm_images.models.enums import PromptScope, ReviewStatus, StepStatus


class Prompt(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_prompt"
    __table_args__ = (
        # Enforced by the database too: two concurrent creates cannot both pass
        # the service's check (an IntegrityError is a 409 ``prompt_name_taken``).
        UniqueConstraint("tenant_id", "collection_id", "name", name="uq_images_prompt_name"),
        # A preset's prompt is created once per collection (``apply_preset``).
        UniqueConstraint(
            "tenant_id", "collection_id", "preset_prompt_id", name="uq_images_prompt_preset_prompt"
        ),
    )

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
    """The preset this prompt came from; its ``cross_check`` runs after a group run."""
    preset_prompt_id: str | None = Field(default=None, max_length=200)
    """The ``PromptSpec.id`` it was created from (``apply_preset`` is idempotent by it)."""
    member_prompt_id: uuid.UUID | None = fk_uuid(
        "images_prompt.id", nullable=True, ondelete="SET NULL"
    )
    """Group scope with ``inputs`` ``results``/``both``: the image-scope prompt
    whose per-member results are consolidated."""
    revision: int = Field(default=1, sa_column_kwargs={"nullable": False})
    """Bumped when the instruction or schema is edited; a result produced under
    an older revision is stale."""


class PromptResult(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_prompt_result"
    # A lease renewal is bookkeeping, not a change anyone audits.
    __audit_exclude_fields__: ClassVar[set[str]] = {
        "lease_token",
        "lease_expires_at",
        "ai_started_at",
        "requested_at",
    }
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
    prompt_revision: int | None = Field(default=None)
    """The ``Prompt.revision`` the output was produced under; older is stale."""
    error: str | None = Field(default=None, max_length=2000)
    cross_check: dict[str, Any] | None = json_null()
    review_status: ReviewStatus = enum_col(ReviewStatus, "review_status", ReviewStatus.UNREVIEWED)
    reviewed_data: dict[str, Any] | None = json_null()
    reviewed_by: str | None = Field(default=None, max_length=255)
    reviewed_at: datetime | None = dt_col()
    history: list[dict[str, Any]] = json_col(list)
    """The last 5 reviewed values, newest first, kept when a re-run resets the review."""
    lease_token: uuid.UUID | None = Field(default=None, sa_column=Column(Uuid, nullable=True))
    """A group run's claim (``sm_images.pipeline.ai.group_lease``); image results leave it null."""
    lease_expires_at: datetime | None = dt_col()
    """A requested (``pending``) or claimed (``running``) group run is in flight until then."""
    ai_started_at: datetime | None = dt_col()
    """Set once per lease before the consolidation call: a redelivery does not pay twice."""
    requested_at: datetime | None = dt_col()
    """When a group run last entered ``pending`` - set by the request alone, so
    reconcile ages a lost dispatch by it, never by a later write's ``updated_at``."""
