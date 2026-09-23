"""Table sets: the global one, the declared collections, and how code finds
the right one.

Phase 5 §6. A **collection** is a physical partition — its own document table,
revision log and six index tables — declared by the host in code because the
tables have to exist in the host's Alembic history and a DB-backed setting read
at boot cannot create any. Everything else stays global (§6.4): the type
tables, the reduce table, settings, permissions, the health check.

The whole feature is designed to be **inert when unused** (§6.5). With no
:func:`declare_collection` call this module builds exactly one table set, whose
tables are the Phase 4 tables under the Phase 4 names,
:func:`tables_for` always returns it, and ``Base.metadata`` holds nothing that
was not there before — asserted against a literal list in
``tests/test_collections_inert.py``, which is the acceptance test the design
names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sm_records import constants
from sm_records.models._base import GLOBAL_PREFIX, collection_prefix
from sm_records.models._index import make_index_tables
from sm_records.models._record import make_record_tables
from sm_records.models._record_tables import RecordTables
from sm_records.schema.types import IndexKind

__all__ = [
    "TableSet",
    "collection_names",
    "declare",
    "is_sealed",
    "seal",
    "table_set",
    "table_sets",
    "tables_for",
    "tables_of",
]

MAX_COLLECTION_NAME_LEN = constants.MAX_COLLECTION_NAME_LEN
RESERVED_COLLECTION_NAMES = constants.RESERVED_COLLECTION_NAMES
"""Re-exported from :mod:`sm_records.constants`, which is where ``models._type``
reads its own constants from — that module must not import this one, whose
import builds every table set. The ``collection`` column's width is
:data:`~sm_records.constants.MAX_COLLECTION_COLUMN_LEN` and is deliberately
wider than the name limit enforced here; see its docstring."""

_KEY_RE = re.compile(constants.TYPE_KEY_PATTERN)


@dataclass(frozen=True, slots=True)
class TableSet:
    """The tables one Record Type's documents live in.

    ``name`` is ``None`` for the global set and the collection's name
    otherwise, which is exactly what ``RecordType.collection`` stores — so
    :func:`tables_for` is a dictionary lookup and never a special case.
    """

    name: str | None
    record: type
    revision: type
    index: dict[IndexKind, type] = field(repr=False)
    slug_index: str
    group_locale_index: str
    uuid_signatures: tuple[str, ...]
    slug_signatures: tuple[str, ...]
    group_locale_signatures: tuple[str, ...]

    @property
    def index_tables(self) -> tuple[type, ...]:
        """Every index kind's table, for code that must touch all six — the
        reindex, the cascade on delete, the tests. In :class:`IndexKind`
        declaration order, so a statement-count test is stable."""
        return tuple(self.index[kind] for kind in IndexKind)


def _build(name: str | None) -> TableSet:
    prefix = GLOBAL_PREFIX if name is None else collection_prefix(name)
    suffix = "" if name is None else "".join(part.title() for part in name.split("_"))
    doc: RecordTables = make_record_tables(prefix, class_suffix=suffix)
    return TableSet(
        name=name,
        record=doc.record,
        revision=doc.revision,
        index=make_index_tables(prefix, class_suffix=suffix),
        slug_index=doc.slug_index,
        group_locale_index=doc.group_locale_index,
        uuid_signatures=doc.uuid_signatures,
        slug_signatures=doc.slug_signatures,
        group_locale_signatures=doc.group_locale_signatures,
    )


GLOBAL = _build(None)
"""The shared set — Phase 4's tables, under Phase 4's names."""

_sets: dict[str | None, TableSet] = {None: GLOBAL}
_by_class: dict[type, TableSet] = {GLOBAL.record: GLOBAL, GLOBAL.revision: GLOBAL}
_sealed = False


def seal() -> None:
    """Refuse further declarations — called once the app is being constructed.

    A collection declared after that point has tables no migration created and
    no ``create_all`` reached, so every write to it would be a
    ``no such table`` at runtime rather than at import. ``RecordsModule.register_settings``
    is where this fires: it is the first hook the host calls, and by then the
    host's own ``records_collections`` import has long since run (§6.6).
    """
    global _sealed
    _sealed = True


def is_sealed() -> bool:
    return _sealed


def _validate(name: str) -> None:
    if not isinstance(name, str) or not _KEY_RE.match(name):
        raise ValueError(
            f"collection name {name!r} must match {constants.TYPE_KEY_PATTERN}, "
            "like a record type key"
        )
    if len(name) > MAX_COLLECTION_NAME_LEN:
        raise ValueError(
            f"collection name {name!r} must be at most {MAX_COLLECTION_NAME_LEN} characters: "
            "it is a table-name prefix, and the longest index built on it "
            "(ix_records_c_<name>_record_type_status_position) has to stay inside "
            "Postgres's 63-byte identifier limit"
        )
    if name in RESERVED_COLLECTION_NAMES:
        raise ValueError(
            f"collection name {name!r} is reserved: "
            f"{', '.join(sorted(RESERVED_COLLECTION_NAMES))} are not available"
        )


def declare(name: str) -> TableSet:
    """Create — or return — the table set called ``name``. See
    :func:`sm_records.collections.declare_collection`, the public front door.

    Idempotent, because a host that imports its declaration module twice (a
    reload, a test that re-imports it) must not get two sets of tables on one
    ``MetaData`` — the second ``CREATE TABLE`` would be a duplicate and the
    error would name the table rather than the double import.
    """
    existing = _sets.get(name)
    if existing is not None:
        return existing
    _validate(name)
    if _sealed:
        raise RuntimeError(
            f"collection {name!r} was declared after the app was built. Tables must exist in "
            "the host's Alembic history, so a collection has to be declared at import time — "
            "call declare_collection() in a module your host imports before create_app()"
        )
    built = _build(name)
    _sets[name] = built
    _by_class[built.record] = built
    _by_class[built.revision] = built
    return built


def collection_names() -> tuple[str, ...]:
    """Every declared collection, sorted. Empty on a host that declares none,
    which is the state §6.5 calls inert."""
    return tuple(sorted(name for name in _sets if name is not None))


def table_sets() -> tuple[TableSet, ...]:
    """The global set followed by every declared collection.

    The order is the global set *first* and then alphabetical, which matters
    to the one caller that iterates all of them and merges the results — "who
    references this record" (:func:`sm_records.services._relations.referrers`)
    — so a referrer list does not reorder itself when a collection is added.
    """
    return (GLOBAL, *(_sets[name] for name in collection_names()))


def table_set(name: str | None) -> TableSet:
    """The set called ``name``, or the global one for ``None``.

    A ``KeyError`` would be the wrong failure: the name reaching here comes
    from ``RecordType.collection``, i.e. from a row, and a row naming a
    collection this process does not declare is an operator error (the host
    stopped declaring it) rather than a bug. It is a ``LookupError`` saying
    which names exist.
    """
    found = _sets.get(name)
    if found is None:
        declared = ", ".join(collection_names()) or "none"
        raise LookupError(
            f"no collection named {name!r} is declared in this process (declared: {declared}); "
            "a record type naming one needs the host to declare_collection() it at import time"
        )
    return found


def tables_for(rtype) -> TableSet:
    """The tables ``rtype``'s documents live in — the whole of §6.3's seam.

    Every place that used to name ``Record``, ``RecordRevision`` or an index
    class by module attribute now asks this instead, so a collection type and a
    global type run the same code against different tables.
    """
    return table_set(getattr(rtype, "collection", None))


def tables_of(record) -> TableSet:
    """The set a *record* belongs to, by its class.

    For the handful of callers that hold a record and no type — the revision
    writer, the trim, the purge. Deriving it from the instance rather than
    threading a ``TableSet`` through them keeps their signatures the shape the
    rest of the module calls them with, and it cannot disagree with the row: the
    class *is* the table.
    """
    cls = record if isinstance(record, type) else type(record)
    found = _by_class.get(cls)
    if found is None:
        raise LookupError(f"{cls.__name__} is not a records document class")
    return found
