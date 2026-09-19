"""SQLModel tables for the Records module.

Every table the module owns is imported here so ``Base.metadata`` is complete
the moment anything imports the package — Alembic autogenerate and the test
harness both rely on that.
"""

from __future__ import annotations

from sm_records.models._base import Base
from sm_records.models._index import (
    IndexBool,
    IndexDate,
    IndexDatetime,
    IndexNumber,
    IndexRef,
    IndexText,
)
from sm_records.models._record import Record, RecordRevision, RecordStatus, RevisionEvent
from sm_records.models._type import RecordType, RecordTypeRevision

INDEX_TABLES: tuple[type, ...] = (
    IndexText,
    IndexNumber,
    IndexBool,
    IndexDate,
    IndexDatetime,
    IndexRef,
)
"""Every index kind, for code that must touch all of them (the reindex, the
cascade on delete, the tests)."""

__all__ = [
    "INDEX_TABLES",
    "Base",
    "IndexBool",
    "IndexDate",
    "IndexDatetime",
    "IndexNumber",
    "IndexRef",
    "IndexText",
    "Record",
    "RecordRevision",
    "RecordStatus",
    "RecordType",
    "RecordTypeRevision",
    "RevisionEvent",
]
