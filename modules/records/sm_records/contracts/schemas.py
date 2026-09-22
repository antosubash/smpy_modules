"""HTTP-facing DTOs for the Records API and admin views — Record Type and
Record CRUD.

SQLModel throughout, per ``CLAUDE.md`` — never a plain pydantic ``BaseModel``.
The read shapes (``TypeRead``, ``RecordRead``, ``RevisionRead``) are built by
:func:`type_read` / :func:`record_read` / :func:`revision_read` rather than
constructed ad hoc at each call site, so the API and the Inertia views render
one serialisation of a row rather than two that can drift.

The schema-change half of the contract — the dry-run report, a preview's
response, and the two revision-listing shapes — lives in
``contracts/schema_change.py``, split out for the 300-line cap. The seam is
real: everything here is "what does one row look like on the wire", and that
module is "what does a proposed change to one look like".
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records.contracts._types import (
    TypeCreate,
    TypeListResponse,
    TypeRead,
    TypeUpdate,
    type_read,
)
from sm_records.contracts.i18n import TranslationRead
from sm_records.contracts.relations import ExpandedRef
from sm_records.contracts.revisions import (
    RecordRevisionDetailRead,
    RecordRevisionRestoreRequest,
    RevisionListResponse,
    RevisionRead,
    record_revision_detail_read,
    revision_read,
)
from sm_records.models import Record, RecordType
from sm_records.schema.fields import FieldDefinition
from sm_records.services._payload import field_defs
from sm_records.services.records import read_view

__all__ = [
    "RecordCreate",
    "RecordPage",
    "RecordRead",
    "RecordRevisionDetailRead",
    "RecordRevisionRestoreRequest",
    "RecordUpdate",
    "RevisionListResponse",
    "RevisionRead",
    "TypeCreate",
    "TypeListResponse",
    "TypeRead",
    "TypeUpdate",
    "record_list_read",
    "record_read",
    "record_revision_detail_read",
    "revision_read",
    "type_read",
]


class RecordRead(SQLModel):
    uuid: str
    type_key: str
    data: dict[str, Any]
    schema_stale: bool
    version: int
    schema_version: int
    status: str
    slug: str | None
    locale: str
    """The language this record is written in, fixed for its lifetime."""
    translation_group: str
    """What this record and its translations share. A record with no siblings
    is alone in a group named after its own uuid."""
    display_title: str
    position: int
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    is_deleted: bool
    invalid: list[dict[str, str]]
    """Empty when the record satisfies the current schema. Non-empty marks it
    "invalid under current schema" without hiding it (design §8.3) — set by a
    ``force``d restrictive schema change or a rollback the record no longer
    fits. Straight from ``read_view``'s own ``invalid`` list.

    **Always empty on a list response** — filling it costs a validator pass
    per row (:func:`record_list_read`); the badge belongs to the editor, which
    reads one record. :attr:`invalid_since` is what a list reads instead."""
    invalid_since: datetime | None
    """When a scan last found this record wanting, or ``null`` — the *stored*
    mark (``services/_invalid.py``), filled on every read including a list.

    The two are the same fact at different resolutions and neither replaces
    the other: ``invalid`` says which fields are wrong *now* and costs a
    validator pass, ``invalid_since`` says that something was wrong and when,
    and costs nothing. A row can carry the timestamp with an empty ``invalid``
    — the payload was fixed in the database rather than through the API, and
    the next write or rescan clears the mark."""
    translations: list[TranslationRead] | None = None
    """Every record in this one's translation group, itself included, **only**
    under ``?translations=true`` on the single-record read and on the record
    editor view (Phase 5 §4.4).

    ``None`` when the caller did not ask, and never filled on a list: it is one
    extra query per *record*, which on a page of fifty is fifty. Trashed
    siblings are listed and flagged — they keep their claim on their language,
    so a panel that hid them would offer an "Add translation" the API can only
    refuse."""
    expanded: dict[str, list[ExpandedRef]] | None = None
    """Relation targets resolved under an explicit ``?expand=a,b`` (design
    §9): field key -> one :class:`ExpandedRef` per stored reference, in payload
    order, so a to-many field's list lines up with ``data[key]``. ``None`` when
    the caller did not ask; a stored reference whose target is trashed, purged
    or not this caller's to see is still listed, flagged rather than dropped.
    Depth is one — an expanded target's own relations stay bare."""


class RecordPage(SQLModel):
    """One page of records, with an honest account of what it does not know.

    ``total`` is exact up to ``RecordsSettings.max_count`` and ``None`` when
    the caller sent ``?total=false``; ``total_capped`` says the real number is
    larger than the ``total`` reported (F4). ``next_cursor`` is the opaque
    ``?after=`` value for the page after this one, ``None`` on the last (F11).
    """

    items: list[RecordRead]
    total: int | None
    page: int
    page_size: int
    total_capped: bool = False
    next_cursor: str | None = None


class RecordCreate(SQLModel):
    data: dict[str, Any] = SQLField(default_factory=dict)
    status: str | None = None
    slug: str | None = None
    locale: str | None = None
    """The language to write this record in (Phase 5 §4.3).

    ``None`` means the configured ``default_content_locale``. A value that is
    not one of ``content_locales`` is a 422 naming it, and a type that is not
    ``translatable`` accepts only the default — a record written into a
    language its type does not offer would be reachable by uuid and by nothing
    else. Set here and nowhere else: a record's language is fixed for its
    lifetime, so there is no ``locale`` on :class:`RecordUpdate`."""
    position: int = 0


class RecordUpdate(SQLModel):
    """No ``locale`` is honoured here — a record's language is fixed for its
    lifetime (Phase 5 §4.3). ``locale`` is nonetheless *declared*, for the same
    reason :attr:`TypeUpdate.key` is: a client sends back the record it just
    read, and SQLModel's default would drop the key silently and answer 200 to
    a request that asked for a language change. ``endpoints/api/records.py``
    refuses a body that carries it, so the answer is a 422 saying why."""

    expected_version: int
    data: dict[str, Any]
    status: str | None = None
    slug: str | None = None
    #: Declared only so a body carrying one is refused, not dropped.
    locale: str | None = None
    position: int | None = None


def record_read(
    rtype: RecordType,
    record: Record,
    *,
    with_invalid: bool = True,
    defs: list[FieldDefinition] | None = None,
    expanded: dict[str, list[ExpandedRef]] | None = None,
    translations: list[TranslationRead] | None = None,
    extra_invalid: Sequence[dict[str, str]] = (),
) -> RecordRead:
    """The one lenient read every caller gets: ``read_view`` fills a missing
    key from ``default`` and flags a row stamped at an old schema version
    rather than failing it (design §8.3).

    ``with_invalid``/``defs`` are ``read_view``'s — see
    :func:`record_list_read`, the one caller that turns the badge off.

    ``data`` still carries the reserved ``_orphaned`` sub-key when the row has
    one: these screens are the admin's, and the raw editor shows a deleted
    field's content on purpose (§8.2 — that is what makes the deletion
    undoable). The public read API strips it — see ``contracts/public.py``.

    ``expanded`` and ``translations`` are passed through untouched: resolving
    either is the service's job (``services/expand.py``,
    ``services/_translations.py``), this only carries them.

    ``extra_invalid`` is appended to the badge. ``read_view``'s own ``invalid``
    is whatever the compiled validator says about *this* payload, which cannot
    cover a rule about a pair of records: a field forced ``unique`` over
    existing duplicates leaves a record whose payload validates perfectly and
    which no write is accepted for. The caller that is willing to pay a query
    per ``unique`` field — the single-record read, never a list — passes
    ``services._duplicates.conflicts_for`` here, so §8.3's "marked, not
    hidden" holds for that class too.
    """
    view = read_view(rtype, record, with_invalid=with_invalid, defs=defs)
    return RecordRead(
        uuid=record.uuid,
        type_key=rtype.key,
        data=view["data"],
        schema_stale=view["schema_stale"],
        version=record.version,
        schema_version=record.schema_version,
        status=record.status.value,
        slug=record.slug,
        locale=record.locale,
        translation_group=record.translation_group,
        display_title=record.display_title,
        position=record.position,
        published_at=record.published_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        is_deleted=record.is_deleted,
        invalid=[*view["invalid"], *extra_invalid],
        invalid_since=record.invalid_since,
        translations=translations,
        expanded=expanded,
    )


def record_list_read(
    rtype: RecordType,
    records: Sequence[Record],
    *,
    expanded: dict[str, dict[str, list[ExpandedRef]]] | None = None,
) -> list[RecordRead]:
    """A page of records, read once per *type* rather than once per row.

    Two things the per-record path does that a list must not: it re-validates
    the type's stored field definitions (``field_defs``) for every item, and it
    runs the compiled payload validator for every item to fill ``invalid``. On
    a page of fifty that is fifty of each, to produce a badge no list screen
    shows — so ``invalid`` is ``[]`` here by construction, and a caller that
    needs it opens the record (design §8.3's "marked, not hidden" is about the
    editor). ``defs`` is computed once and shared.

    ``expanded`` is the whole page's expansion keyed by record uuid — what
    ``services.expand.expand`` returns — and is *looked up* here rather than
    resolved: one batched query per relation field for the page is the rule
    (§9), so a per-row query hiding behind this signature would be exactly the
    regression it exists to prevent.
    """
    defs = field_defs(rtype)
    return [
        record_read(
            rtype,
            record,
            with_invalid=False,
            defs=defs,
            expanded=None if expanded is None else expanded.get(record.uuid, {}),
        )
        for record in records
    ]
