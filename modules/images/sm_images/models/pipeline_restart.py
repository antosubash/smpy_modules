"""A collection restart in progress: the durable record reconcile resumes from.

``cursor`` is the last image id whose reset committed. It advances in the
same transaction as that reset, conditionally on its previous value, so each
image is reset at most once per restart even if two runners (a live worker
and reconcile) race on one record. ``heartbeat_at`` moves with every image;
reconcile picks up records whose heartbeat is stale and not ``finished_at``.
A restart whose starter lost the right is finished early, never resumed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from simple_module_db.mixins import AuditMixin, MultiTenantMixin
from sqlalchemy import Column, Uuid
from sqlmodel import Field

from sm_images.models._base import Base
from sm_images.models._cols import dt_col, fk_uuid, pk_uuid


class PipelineRestart(Base, AuditMixin, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "images_pipeline_restart"

    id: uuid.UUID = pk_uuid()
    collection_id: uuid.UUID = fk_uuid("images_collection.id", ondelete="CASCADE")
    scope: str = Field(max_length=10)
    cursor: uuid.UUID | None = Field(default=None, sa_column=Column(Uuid, nullable=True))
    heartbeat_at: datetime | None = dt_col(index=True)
    finished_at: datetime | None = dt_col()
    run_as: str | None = Field(default=None, max_length=255)
    """Who started the restart. Owner or ``images.manage`` only; the runner
    re-checks it before each chunk (``sm_images.starter_right``)."""
    access_basis: str | None = Field(default=None, max_length=10)
    """``owner`` or ``manage``: where ``run_as``'s right came from."""
