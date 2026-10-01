"""Collections — giving one Record Type its own physical tables. Phase 5 §6.

YesSql partitions documents into separate tables per *collection*, and the
original design (§12) kept the option open by putting ``type_id`` on every
index row. This is that option cashed in, with the smallest surface it can
have.

**Declaration is code, not configuration.** The tables have to exist in the
host's Alembic history, so a collection cannot be a DB-backed setting read at
boot. The host declares it in a module imported before ``create_app``::

    # host/records_collections.py, imported by host/main.py
    from sm_records.collections import declare_collection

    declare_collection("events")

That call builds a full table set on the module's own ``Base.metadata`` with
the prefix ``records_c_events_`` — ``record``, ``revision`` and the six index
tables, each built by the *same factory* that builds the global ones and
therefore identical in shape modulo the prefix. The host then autogenerates one
migration for the new tables, exactly as it did for the module itself.

**Assignment is per type, at creation only** (§6.2). ``POST /types`` takes
``collection``; ``PATCH`` refuses to change it with a 409, because moving a
populated type between collections is a data migration with no rollback story.

**What stays global** (§6.4): ``records_type``, ``records_type_revision``, the
reduce table (keyed by ``type_id``, with no ``record_id`` to partition on),
settings, permissions, the health check and the CLI, which takes a type and
follows its collection.

**Inert when unused** (§6.5): with no call to :func:`declare_collection` the
module's metadata is the Phase 4 metadata, ``alembic check`` reports no
operations, and :func:`tables_for` always answers with the global set.
"""

from __future__ import annotations

from sm_records.models._tables import (
    MAX_COLLECTION_NAME_LEN,
    RESERVED_COLLECTION_NAMES,
    TableSet,
    collection_names,
    declare,
    table_set,
    tables_for,
)

__all__ = [
    "MAX_COLLECTION_NAME_LEN",
    "RESERVED_COLLECTION_NAMES",
    "TableSet",
    "collections",
    "declare_collection",
    "table_set",
    "tables_for",
]


def declare_collection(name: str) -> TableSet:
    """Declare a collection and build its tables. See the module docstring.

    ``name`` matches ``TYPE_KEY_PATTERN``, is at most
    :data:`MAX_COLLECTION_NAME_LEN` characters, and is not one of
    :data:`RESERVED_COLLECTION_NAMES` — a ``ValueError`` otherwise, raised at
    import time where there is a person reading a traceback.

    Calling it twice with the same name is a no-op that returns the same
    :class:`TableSet`; calling it after the app has been constructed is a
    ``RuntimeError``, because those tables are in no migration and no
    ``create_all`` and every write to them would be a ``no such table``
    discovered at runtime instead.
    """
    return declare(name)


def collections() -> tuple[str, ...]:
    """Every declared collection name, sorted.

    The registry §6.1 names. Read by ``TypeCreate``'s validation (so an
    unknown one is a 422 listing the declared set), by the type editor's view
    props and by ``make doctor``-style checks that want to know what this
    process partitions.
    """
    return collection_names()
