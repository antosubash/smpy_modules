"""Wire shapes for import and export — the report, and the type definition.

Two contracts, both deliberately small.

:class:`ImportReport` is what *every* import returns, dry run or not, refused
or not. A dry run and a real run differ in one boolean and in nothing else,
because the whole point of the dry run is to be able to read it and then press
the button: a report whose shape changed once the write actually happened
would be a report nobody could rehearse against. It is also what rides along
with the refusal when ``on_error=abort`` finds a bad row (see
``services.errors.ImportRefused``), so the 422 body and the 200 body are the
same object.

:class:`TypeExport` is deliberately ``TypeCreate``-shaped and not
``TypeRead``-shaped: a type definition you can post straight back at
``POST /types/import``. ``record_count``, ``version``, ``schema_version`` and
``reindex_pending`` are all facts about *this* install's copy of the type, and
carrying them into a file that is going to be imported somewhere else would
invite a reader to believe they meant something there.
"""

from __future__ import annotations

import enum
from typing import Any

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records.models import RecordType

__all__ = [
    "ERROR_CAP",
    "ImportFormat",
    "ImportMode",
    "ImportReport",
    "ImportRowError",
    "OnError",
    "TypeExport",
    "TypeImportRequest",
    "type_export",
]

ERROR_CAP = 200
"""How many row errors a report carries. A 100k-row file with a mismatched
header fails every row, and 100k copies of one message is a response nobody
can read and a payload that can outgrow the file it describes. The count in
``failed`` stays exact; ``errors_truncated`` says the list is not."""


class ImportFormat(str, enum.Enum):  # noqa: UP042
    JSON = "json"
    CSV = "csv"


class ImportMode(str, enum.Enum):  # noqa: UP042
    """What an incoming row is allowed to do to the type.

    ``UPSERT`` is the default because it is the one that makes an export
    round-trip: re-importing a file you exported should converge, not fail on
    the first row it already has. ``CREATE`` and ``UPDATE`` exist for the
    cases where converging is exactly what you do *not* want — a load of new
    content that must not silently overwrite, and a correction pass that must
    not silently invent.
    """

    UPSERT = "upsert"
    CREATE = "create"
    UPDATE = "update"


class OnError(str, enum.Enum):  # noqa: UP042
    """``ABORT`` is all-or-nothing: the request's transaction is rolled back,
    so a file that fails on row 501 leaves the first 500 unwritten. ``SKIP``
    writes what it can and reports the rest."""

    ABORT = "abort"
    SKIP = "skip"


class ImportRowError(SQLModel):
    """One thing wrong with one row.

    ``row`` is 1-based and counts *data* rows, not file lines — for CSV the
    header is not row 1, because a spreadsheet does not number it that way
    either and the point of the number is to be findable.
    """

    row: int
    uuid: str | None = None
    field: str | None = None
    message: str


class ImportReport(SQLModel):
    """The outcome of one import, whether or not it wrote anything.

    ``created + updated + skipped + failed == total``. ``skipped`` is not a
    failure state: it counts rows that matched a record the file already
    agrees with, which is what makes re-importing an export a no-op rather
    than a version bump on every record in the type.
    """

    dry_run: bool
    mode: ImportMode
    total: int
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[ImportRowError] = SQLField(default_factory=list)
    errors_truncated: bool = False
    duration_ms: int = 0


class TypeExport(SQLModel):
    """A record type's definition, in the shape ``POST /types/import`` takes."""

    key: str
    label: str
    label_plural: str
    description: str | None = None
    icon: str | None = None
    fields: list[dict[str, Any]] = SQLField(default_factory=list)
    display_field: str | None = None
    slug_field: str | None = None
    is_public: bool = False
    show_in_menu: bool = False
    """Carried so a type that had its own sidebar entry where it was exported
    still has one where it is imported — the same round-trip rule ``is_public``
    obeys, and the reason an export is a definition rather than a snapshot of
    half of one."""
    translatable: bool = False
    """Carried so a definition exported from a multilingual install arrives at
    the next one still able to hold translations (Phase 5 §4.1)."""
    allowed_roles: list[str] = SQLField(default_factory=list)
    collection: str | None = None
    """Which table set this type's documents live in (Phase 5 §6.2).

    A property of the *definition*, not of this install's copy of it — unlike
    ``record_count`` or ``version``, which is why those do not travel and this
    does. Dropped from the export, a collection-backed type landed on the next
    install as a shared-tables type with no warning anywhere, and an explicit
    ``collection`` in an import body was ignored rather than refused, while the
    same value on ``POST /types`` was a clean 422.

    It reaches ``create_type`` on a create, so an undeclared name is that same
    422; on ``mode=update`` a value that differs from the stored one is the 409
    ``PUT /types/{key}`` already gives, because a collection is assigned at
    creation and never after. An echo of the current value is not a change and
    is dropped, so re-importing this install's own export is unaffected.
    """


class TypeImportRequest(TypeExport):
    """:class:`TypeExport` plus the three knobs the §8 pipeline needs.

    ``mode="update"`` routes through the ordinary ``update_type`` path, so a
    schema import onto a populated type is classified, dry-run and refused
    exactly as the same change made in the editor would be — including
    answering a refusal with ``force`` or ``orphaned``. That is the whole
    reason this does not write ``fields`` itself.
    """

    mode: str = "create"
    expected_version: int | None = None
    force: bool = False
    orphaned: str | None = None


def type_export(rtype: RecordType) -> TypeExport:
    return TypeExport.model_validate(rtype)
