"""An ``.ics`` import: the job, and the items staged for it (one per VEVENT)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Column, Index, LargeBinary, UniqueConstraint
from sqlmodel import Field

from sm_events.core.constants import TITLE_MAX, UID_MAX
from sm_events.models._base import Base
from sm_events.models._cols import big_pk, counter, dt_col, fk_big, fk_uuid, flag, json_col

_STATUS_LEN = 24
_CODE_LEN = 40


class EventImport(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_import"
    __table_args__ = (
        Index("ix_events_import_at", "tenant_id", "created_at"),
        Index("ix_events_import_status", "status", "lease_until"),
        # An id appears in URLs, and ``INTEGER PRIMARY KEY`` on SQLite reuses the highest one
        # after a delete (Postgres sequences never do).
        {"sqlite_autoincrement": True},
    )

    id: int | None = big_pk()
    calendar_id: uuid.UUID = fk_uuid("events_calendar.id", ondelete="CASCADE")
    created_by: str = Field(max_length=64)
    status: str = Field(max_length=_STATUS_LEN)
    """An import state (``constants.IMPORT_STATES``)."""
    filename: str = Field(max_length=200)
    size_bytes: int = counter()
    source: bytes | None = Field(default=None, sa_column=Column(LargeBinary, nullable=True))
    """The raw upload; ``NULL`` once the parse step has staged its items."""
    publish: bool = flag()
    may_publish: bool = flag()
    """The applier's ``events.publish`` when they applied: the worker has no session to ask."""
    grants: list[str] = json_col(list)
    """The importer's ``events.*`` permissions when they uploaded and again when they applied. A
    worker builds no app (no directory, no grant sources), so this is what it can check the
    calendar's policy with: share, ownership and trash are read fresh for every item, the
    permissions are as of the launch."""
    total: int = counter()
    counts: dict[str, Any] = json_col(dict)
    reasons: dict[str, Any] = json_col(dict)
    dropped: dict[str, Any] = json_col(dict)
    created: int = counter()
    updated: int = counter()
    unchanged: int = counter()
    skipped: int = counter()
    failed: int = counter()
    processed: int = counter()
    error_code: str | None = Field(default=None, max_length=_CODE_LEN)
    lease_owner: str | None = Field(default=None, max_length=36)
    lease_until: datetime | None = dt_col()
    created_at: datetime = dt_col(nullable=False)
    updated_at: datetime = dt_col(nullable=False)
    finished_at: datetime | None = dt_col()


class EventImportItem(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "events_import_item"
    __table_args__ = (
        UniqueConstraint("tenant_id", "import_id", "seq", name="uq_events_import_item_seq"),
        Index("ix_events_import_item_todo", "tenant_id", "import_id", "outcome"),
        {"sqlite_autoincrement": True},
    )

    id: int | None = big_pk()
    import_id: int = fk_big("events_import.id", ondelete="CASCADE")
    seq: int = Field(sa_column_kwargs={"nullable": False})
    uid: str = Field(max_length=UID_MAX)
    verdict: str = Field(max_length=_STATUS_LEN)
    reason: str | None = Field(default=None, max_length=_CODE_LEN)
    notes: list[str] = json_col(list)
    title: str = Field(max_length=TITLE_MAX)
    starts_at: datetime | None = dt_col()
    all_day: bool = flag()
    recurring: bool = flag()
    existing_event_id: uuid.UUID | None = Field(default=None, sa_column_kwargs={"nullable": True})
    """The live event a ``update`` verdict targets. No foreign key: a trashed or purged event
    is the apply step's ``changed_since_preview``, not a constraint error."""
    expected_revision: int | None = Field(default=None, sa_column_kwargs={"nullable": True})
    payload: dict[str, Any] = json_col(dict)
    """The mapped event, as JSON. Held until the import is deleted."""
    outcome: str | None = Field(default=None, max_length=_STATUS_LEN)
    """``None`` is still to do."""
    outcome_code: str | None = Field(default=None, max_length=_CODE_LEN)
    event_id: uuid.UUID | None = Field(default=None, sa_column_kwargs={"nullable": True})
