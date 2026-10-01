"""``declare_collection``: what it accepts, what it refuses, and when.

Everything here is about the registry itself — names, idempotence, the seal,
and the three lookups (:func:`tables_for`, :func:`table_set`,
:func:`tables_of`) that every other module in the package now goes through.
The *tables* it builds are ``test_collections_ddl.py``'s subject and the
inert-when-unused property is ``test_collections_inert.py``'s.
"""

from __future__ import annotations

import pytest
from sm_records.collections import collections, declare_collection
from sm_records.constants import MAX_COLLECTION_NAME_LEN, RESERVED_COLLECTION_NAMES
from sm_records.models import GLOBAL, RecordType, table_set, table_sets, tables_for, tables_of
from sm_records.models import _tables as registry

from tests.collections_harness import COLLECTION_NAMES, EVENTS


@pytest.fixture
def unsealed():
    """Reopen the registry for one test and close it again.

    The seal is process-global and ``RecordsModule.register_settings`` sets it
    the first time any API test builds an app, so by the time this file runs it
    is almost certainly already closed. Saving and restoring the flag is the
    only way to exercise both sides of it in one process — and restoring it is
    what stops this test leaving the registry open for the rest of the session.
    """
    was = registry.is_sealed()
    registry._sealed = False
    yield
    registry._sealed = was


def test_collections_lists_what_was_declared():
    assert collections() == COLLECTION_NAMES


def test_declaring_the_same_name_twice_returns_the_same_table_set(unsealed):
    """Idempotent because a host may import its declaration module twice — a
    reload, a test re-import — and a second set of tables on one ``MetaData``
    would fail as a duplicate ``CREATE TABLE`` naming the table rather than the
    double import."""
    assert declare_collection("events") is EVENTS
    assert collections() == COLLECTION_NAMES


@pytest.mark.parametrize(
    "name",
    ["Events", "1events", "ev-ents", "ev ents", "", "x" * (MAX_COLLECTION_NAME_LEN + 1)],
)
def test_a_name_that_is_not_a_key_is_refused(name, unsealed):
    with pytest.raises(ValueError):
        declare_collection(name)
    assert collections() == COLLECTION_NAMES


@pytest.mark.parametrize("name", sorted(RESERVED_COLLECTION_NAMES))
def test_reserved_names_are_refused(name, unsealed):
    with pytest.raises(ValueError) as excinfo:
        declare_collection(name)
    assert "reserved" in str(excinfo.value)


def test_declaring_after_the_app_is_built_is_refused():
    """§6.1. The tables of a collection declared now are in no migration and
    no ``create_all``, so every write to it would be a ``no such table``
    discovered at runtime — which is a far worse place to find out."""
    registry.seal()
    with pytest.raises(RuntimeError) as excinfo:
        declare_collection("too_late")
    assert "declare_collection" in str(excinfo.value)
    assert "too_late" not in collections()


def test_a_refused_declaration_leaves_no_tables_behind(unsealed):
    from sm_records.models import Base

    before = set(Base.metadata.tables)
    with pytest.raises(ValueError):
        declare_collection("default")
    assert set(Base.metadata.tables) == before


def test_tables_for_answers_from_the_types_collection_column():
    assert tables_for(RecordType(key="a", label="A", label_plural="As")) is GLOBAL
    typed = RecordType(key="b", label="B", label_plural="Bs", collection="events")
    assert tables_for(typed) is EVENTS


def test_table_set_names_what_is_declared_when_asked_for_something_else():
    """A ``LookupError`` and not a ``KeyError``: the name reaching here came
    off a stored row, so a row naming a collection this process does not
    declare is an operator error — the host stopped declaring it — and the
    message has to say which names do exist."""
    with pytest.raises(LookupError) as excinfo:
        table_set("nope")
    assert "events" in str(excinfo.value)


def test_tables_of_answers_from_a_records_class():
    """The three callers that hold a row and no type — the revision writer,
    the trim, the purge — take their table set from the class, which cannot
    disagree with the row about where it came from."""
    assert tables_of(GLOBAL.record) is GLOBAL
    assert tables_of(EVENTS.record(type_id=1, schema_version=1)) is EVENTS
    assert tables_of(EVENTS.revision) is EVENTS
    with pytest.raises(LookupError):
        tables_of(RecordType)


def test_table_sets_puts_the_global_set_first_and_then_sorts():
    """The order matters to the one caller that iterates all of them and
    merges the results — "who references this record" — so adding a collection
    must not reorder an existing referrer list."""
    assert [t.name for t in table_sets()] == [None, "archive", "events"]


def test_a_collections_classes_are_distinct_from_the_global_ones():
    """Not subclasses, and not the same class under two table names: a
    ``isinstance(x, Record)`` check therefore does **not** see a collection's
    record, which is why ``endpoints.api._errors`` asks ``table_sets()``."""
    assert EVENTS.record is not GLOBAL.record
    assert not issubclass(EVENTS.record, GLOBAL.record)
    assert EVENTS.record.__name__ == "RecordEvents"
    assert str(EVENTS.record.__tablename__) == "records_c_events_record"
