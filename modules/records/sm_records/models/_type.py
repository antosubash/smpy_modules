"""Record Types — the runtime-defined schemas — and their revision log."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from simple_module_db.mixins import AuditMixin
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index
from sqlmodel import Field

from sm_records.constants import MAX_COLLECTION_NAME_LEN, MAX_KEY_LEN, MAX_LABEL_LEN
from sm_records.models._base import TYPE_REVISION_TABLE, TYPE_TABLE, Base


class RecordType(Base, AuditMixin, table=True):  # ty: ignore[unsupported-base]
    """A user-defined content type.

    ``fields`` is the whole schema, as JSON. Changing it is an ``UPDATE`` of
    this one row — no DDL anywhere. What happens to the records already stored
    against the old shape is the design doc's §8, and it hinges on two columns
    here: ``schema_version``, stamped onto every record write so a row knows
    which shape it was written in, and ``reindex_pending``, the operational
    marker for fields whose index rows are mid-rebuild.
    """

    __tablename__ = TYPE_TABLE

    id: int | None = Field(default=None, primary_key=True)

    key: str = Field(max_length=MAX_KEY_LEN, unique=True, index=True)
    """Stable identifier used in URLs, the API and relation targets.
    Immutable after creation — a rename would strand all three."""

    label: str = Field(max_length=MAX_LABEL_LEN)
    label_plural: str = Field(max_length=MAX_LABEL_LEN)
    description: str | None = Field(default=None, max_length=1000)
    icon: str | None = Field(default=None, max_length=64)
    """A lucide icon name, for the type list."""

    fields: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, default=list),
    )
    """Ordered field definitions. Validated shape: ``sm_records.schema.fields``."""

    schema_version: int = Field(default=1, sa_column_kwargs={"nullable": False})
    """Bumped on every change to ``fields``. Every record stamps the version it
    was last written against; the validator cache is keyed on it."""

    display_field: str | None = Field(default=None, max_length=MAX_KEY_LEN)
    """Which field's value becomes ``Record.display_title``."""
    slug_field: str | None = Field(default=None, max_length=MAX_KEY_LEN)

    collection: str | None = Field(default=None, max_length=MAX_COLLECTION_NAME_LEN)
    """Which **table set** this type's documents live in — Phase 5 §6.2.

    ``None`` is the global tables, which is what every type written before this
    column existed carries and what every type carries on a host that declares
    no collection. A non-null value names a collection the host declared in
    code (:func:`sm_records.collections.declare_collection`); every read and
    write resolves it through ``models.tables_for(rtype)``.

    **Set on create and never changed.** ``PUT /types/{key}`` refuses it with a
    409:
    moving a populated type between collections would mean copying its records,
    revisions and index rows into other tables and re-pointing every reference
    at them, with no rollback story — so the refusal is the honest answer, and
    a host that wants the move exports and re-imports under a new type.

    Nullable with no backfill on purpose: that is what makes the migration
    additive and the feature inert on a host that never uses it (§6.5).
    """

    is_public: bool = Field(default=False)
    """Gates the anonymous read API. Off by default."""

    translatable: bool = Field(default=False)
    """Whether this type's records may be authored in more than one content
    locale (Phase 5 §4.1).

    Off by default, which is what keeps content i18n inert on a host that never
    asks for it: a type that is not translatable has every record in the
    default content locale, shows no language UI, and refuses a create naming
    any other locale.

    Flipping it **on** is additive — existing records already carry the default
    locale. Flipping it **off** while records in another locale exist is
    refused with a 409 (``services._type_update``), because those records would
    otherwise become unreachable through a UI that no longer offers their
    language."""

    allowed_roles: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, default=list),
    )
    """Roles permitted to write, on top of the static permission. Empty means
    any role holding the permission. Invisible in the framework's role editor —
    design doc §10."""

    version: int = Field(default=1, sa_column_kwargs={"nullable": False})
    """Optimistic concurrency on the schema itself. Design doc §8.6."""

    reindex_pending: dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, default=dict),
    )
    """Field keys whose index rows are being rebuilt, each mapped to the
    ISO-8601 UTC instant the rebuild was enqueued at.

    A mapping rather than the list design §8.5 first described, because §8.9's
    health check has to answer "has this been pending *too long*" — an orphaned
    reindex, whose background task died with the worker that owned it, is
    recoverable but silent, and a bare list of keys cannot say when it started.
    The column is plain ``JSON``, so this costs no migration.

    The reserved key ``"*"`` means "rebuild the whole type", which is what a
    ``display_field`` change enqueues: every record's ``display_title`` is
    denormalised from it (§18 Q2). No field can collide with it —
    ``TYPE_KEY_PATTERN`` requires a lowercase letter first — so a ``"*"``
    marker never refuses a filter.

    Operational state kept *outside* ``fields`` so a revision snapshot never
    captures it: a rollback could otherwise resurrect an ``indexing`` marker.
    """


class RecordTypeRevision(Base, table=True):  # ty: ignore[unsupported-base]
    """Append-only snapshot of a type's schema, one row per change.

    Tiny by construction — types are few and schema edits are rare — and never
    capped: it is what makes a bad schema edit reversible, and a bad schema
    edit damages every row of the type at once.
    """

    __tablename__ = TYPE_REVISION_TABLE
    __table_args__ = (Index("ix_records_type_revision_type_version", "type_id", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    type_id: int = Field(
        sa_column=Column(ForeignKey(f"{TYPE_TABLE}.id", ondelete="CASCADE"), nullable=False)
    )
    version: int = Field(sa_column_kwargs={"nullable": False})
    """The ``RecordType.version`` this snapshot *produced*."""
    schema_version: int = Field(sa_column_kwargs={"nullable": False})
    fields: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, default=list),
    )
    display_field: str | None = Field(default=None, max_length=MAX_KEY_LEN)
    slug_field: str | None = Field(default=None, max_length=MAX_KEY_LEN)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_by: str | None = Field(default=None, max_length=255)
