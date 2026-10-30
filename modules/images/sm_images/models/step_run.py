"""One pipeline step's state for one image."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import Column, Index, UniqueConstraint, Uuid
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, enum_col, fk_uuid, json_null
from sm_images.models.enums import StepStatus


class StepRun(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_step_run"
    __table_args__ = (
        UniqueConstraint("image_id", "step", name="uq_images_step_run_image_step"),
        Index("ix_images_step_run_status_lease", "status", "lease_expires_at"),
    )
    # A lease renewal is bookkeeping, not a change anyone audits.
    __audit_exclude_fields__: ClassVar[set[str]] = {
        "lease_token",
        "lease_expires_at",
        "ai_started_at",
    }

    id: int | None = Field(default=None, primary_key=True)
    image_id: uuid.UUID = fk_uuid("images_image.id", ondelete="CASCADE")
    step: str = Field(max_length=100)
    status: StepStatus = enum_col(StepStatus, "step_status", StepStatus.PENDING)
    attempts: int = Field(default=0, sa_column_kwargs={"nullable": False})
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=2000)
    started_at: datetime | None = dt_col()
    finished_at: datetime | None = dt_col()
    step_version: int | None = Field(default=None)
    prompt_revision: int | None = Field(default=None)
    """For ``prompt:*`` steps: the ``Prompt.revision`` the output was produced under."""
    lease_token: uuid.UUID | None = Field(default=None, sa_column=Column(Uuid, nullable=True))
    """Fences a stale worker: every completion/publish is conditional on it."""
    lease_expires_at: datetime | None = dt_col()
    ai_started_at: datetime | None = dt_col()
    """Set once per lease before an AI step calls its provider: a redelivered
    message for the same lease finds it set and makes no second (paid) call.
    Cleared by every claim and reset."""
    output: dict[str, Any] | None = json_null()
