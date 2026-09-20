"""The module's declarative base, and the table names built on it.

Alone in its own file so every model file can import it without importing each
other — the cycle that would otherwise appear the moment two model files need to
reference the same Base.

Every physical table this module owns is ``<prefix><suffix>``. The global set
carries :data:`GLOBAL_PREFIX`; a **collection** (Phase 5 §6) carries
``records_c_<name>_`` and repeats the same suffixes, which is what lets one
factory build both and one test compare their DDL modulo the prefix. The
suffixes are therefore the real constants here and the familiar full names are
derived from them, so a collection can never be spelled a second way.
"""

from __future__ import annotations

from simple_module_db.base import create_module_base

Base = create_module_base("records")

GLOBAL_PREFIX = "records_"
"""What the shared table set is prefixed with — the Phase 4 names, unchanged."""

COLLECTION_INFIX = "c_"
"""What separates a collection's name from the module prefix.

``records_c_<name>_`` rather than ``records_<name>_``: a collection name obeys
``TYPE_KEY_PATTERN`` and could otherwise be chosen as ``index`` or ``type``,
and ``records_type_record`` would then be a table whose name says nothing
about which of the two things it is.
"""


def collection_prefix(name: str) -> str:
    """The table prefix of a declared collection — Phase 5 §6.1."""
    return f"{GLOBAL_PREFIX}{COLLECTION_INFIX}{name}_"


RECORD_SUFFIX = "record"
REVISION_SUFFIX = "revision"
INDEX_TEXT_SUFFIX = "index_text"
INDEX_NUMBER_SUFFIX = "index_number"
INDEX_BOOL_SUFFIX = "index_bool"
INDEX_DATE_SUFFIX = "index_date"
INDEX_DATETIME_SUFFIX = "index_datetime"
INDEX_REF_SUFFIX = "index_ref"

TYPE_TABLE = "records_type"
TYPE_REVISION_TABLE = "records_type_revision"
"""The type tables are **global and stay global** (§6.4): a collection
partitions documents, and a type is what says which partition its documents
live in."""

RECORD_TABLE = f"{GLOBAL_PREFIX}{RECORD_SUFFIX}"
REVISION_TABLE = f"{GLOBAL_PREFIX}{REVISION_SUFFIX}"
INDEX_TEXT_TABLE = f"{GLOBAL_PREFIX}{INDEX_TEXT_SUFFIX}"
INDEX_NUMBER_TABLE = f"{GLOBAL_PREFIX}{INDEX_NUMBER_SUFFIX}"
INDEX_BOOL_TABLE = f"{GLOBAL_PREFIX}{INDEX_BOOL_SUFFIX}"
INDEX_DATE_TABLE = f"{GLOBAL_PREFIX}{INDEX_DATE_SUFFIX}"
INDEX_DATETIME_TABLE = f"{GLOBAL_PREFIX}{INDEX_DATETIME_SUFFIX}"
INDEX_REF_TABLE = f"{GLOBAL_PREFIX}{INDEX_REF_SUFFIX}"

INDEX_REDUCE_TABLE = f"{GLOBAL_PREFIX}index_reduce"
"""The reduce table is global too, and deliberately (§6.4): a reduce row is a
fold keyed by ``type_id`` with no ``record_id`` to partition on, so it has
nothing to gain from a collection's tables and one more table to rebuild if it
had them."""
