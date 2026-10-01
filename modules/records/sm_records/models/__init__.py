"""SQLModel tables for the Records module.

Every table the module owns is reachable from here so ``Base.metadata`` is
complete the moment anything imports the package — Alembic autogenerate and the
test harness both rely on that.

The names below are the **global** table set (:data:`~sm_records.models._tables.GLOBAL`).
They stay module attributes because the framework's listeners, the host and
every caller that has no Record Type in hand import them, and because a host
that declares no collection has no other set. Code that *does* have a type asks
:func:`tables_for` instead — Phase 5 §6.3.
"""

from __future__ import annotations

from sm_records.models._base import Base
from sm_records.models._record import (
    RecordStatus,
    RevisionEvent,
    new_uuid,
)
from sm_records.models._reduce import REDUCE_GROUP_INDEX_NAME, IndexReduce
from sm_records.models._tables import (
    GLOBAL,
    TableSet,
    collection_names,
    table_set,
    table_sets,
    tables_for,
    tables_of,
)
from sm_records.models._type import RecordType, RecordTypeRevision
from sm_records.schema.types import IndexKind

Record = GLOBAL.record
RecordRevision = GLOBAL.revision
IndexText = GLOBAL.index[IndexKind.TEXT]
IndexNumber = GLOBAL.index[IndexKind.NUMBER]
IndexBool = GLOBAL.index[IndexKind.BOOL]
IndexDate = GLOBAL.index[IndexKind.DATE]
IndexDatetime = GLOBAL.index[IndexKind.DATETIME]
IndexRef = GLOBAL.index[IndexKind.REF]

INDEX_TABLES: tuple[type, ...] = GLOBAL.index_tables
"""Every index kind of the **global** set, for code that must touch all of them
and has no type in hand. A collection's are ``tables_for(rtype).index_tables``."""

__all__ = [
    "GLOBAL",
    "INDEX_TABLES",
    "REDUCE_GROUP_INDEX_NAME",
    "Base",
    "IndexBool",
    "IndexDate",
    "IndexDatetime",
    "IndexNumber",
    "IndexReduce",
    "IndexRef",
    "IndexText",
    "Record",
    "RecordRevision",
    "RecordStatus",
    "RecordType",
    "RecordTypeRevision",
    "RevisionEvent",
    "TableSet",
    "collection_names",
    "new_uuid",
    "table_set",
    "table_sets",
    "tables_for",
    "tables_of",
]
