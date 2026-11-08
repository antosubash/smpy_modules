"""A Mailchimp import: the job, and the rows staged for it (one per address)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from simple_module_db.mixins import MultiTenantMixin
from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field

from sm_newsletter.core.constants import MAX_EMAIL_LEN, MAX_TYPE_KEY_LEN
from sm_newsletter.models._base import Base
from sm_newsletter.models._cols import STATUS_LEN, big_pk, counter, dt_col, fk, json_col


class ImportJob(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_import"
    __table_args__ = (
        Index("ix_newsletter_import_at", "tenant_id", "created_at"),
        Index("ix_newsletter_import_status", "status", "lease_until"),
        # ``?id=`` and a stale tab's discard name an import by id, so an id must
        # never come back: plain ``INTEGER PRIMARY KEY`` on SQLite reuses the
        # highest one after a delete (Postgres sequences never do).
        {"sqlite_autoincrement": True},
    )

    id: int | None = big_pk()
    list_type_key: str = Field(max_length=MAX_TYPE_KEY_LEN)
    status: str = Field(max_length=STATUS_LEN)
    """An ``ImportState`` (``imports.constants.STATES``)."""
    files: list[dict[str, Any]] = json_col(list)
    """``[{name, kind, rows}]``; the name is at most 200 characters."""
    columns: list[dict[str, Any]] = json_col(list)
    """``[{key, header}]``: the mappable columns, the index is the position."""
    mapping: dict[str, Any] = json_col(dict)
    """``{"fields": {"<column index>": "<field key>"}, "tags": bool}``."""
    tags_found: list[dict[str, Any]] = json_col(list)
    """``[{label, value, count}]``, most frequent first."""
    tags_added: bool = Field(default=False, sa_column_kwargs={"nullable": False})
    total: int = counter()
    duplicates: int = counter()
    invalid: int = counter()
    processed: int = counter()
    created: int = counter()
    updated: int = counter()
    skipped: int = counter()
    suppressed: int = counter()
    failed: int = counter()
    errors: list[dict[str, Any]] = json_col(list)
    """``[{file, line, code, field}]``, at most ``KEEP_ERRORS``; never a value."""
    errors_total: int = counter()
    error_code: str | None = Field(default=None, max_length=STATUS_LEN)
    """Why ``status`` is ``failed``."""
    lease_owner: str | None = Field(default=None, max_length=36)
    lease_until: datetime | None = dt_col()
    created_by: str | None = Field(default=None, max_length=64)
    created_at: datetime = dt_col(nullable=False)
    started_at: datetime | None = dt_col()
    finished_at: datetime | None = dt_col()


class ImportEntry(Base, MultiTenantMixin, table=True):  # ty: ignore[unsupported-base]
    __tablename__ = "newsletter_import_row"
    __table_args__ = (
        UniqueConstraint("tenant_id", "import_id", "email_hash", name="uq_newsletter_import_row"),
        Index("ix_newsletter_import_row_todo", "tenant_id", "import_id", "outcome", "seq"),
    )

    id: int | None = big_pk()
    import_id: int = fk("newsletter_import.id", ondelete="CASCADE", big=True)
    seq: int = Field(sa_column_kwargs={"nullable": False})
    file_index: int = Field(sa_column_kwargs={"nullable": False})
    line: int = Field(sa_column_kwargs={"nullable": False})
    kind: str = Field(max_length=16)
    """``subscribed``, ``unsubscribed`` or ``cleaned``."""
    email: str = Field(max_length=MAX_EMAIL_LEN)
    email_hash: str = Field(max_length=64)
    fields: dict[str, Any] = json_col(dict)
    """``{"<column index>": value}``, non-empty cells only."""
    tags: list[str] = json_col(list)
    event_at: datetime | None = dt_col()
    """The confirm/opt-in, unsubscribe or clean time."""
    consent_at: datetime | None = dt_col()
    outcome: str | None = Field(default=None, max_length=32)
    """``None`` is still to do."""
