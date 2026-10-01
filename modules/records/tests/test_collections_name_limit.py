"""``MAX_COLLECTION_NAME_LEN`` is a measurement, so measure it.

A collection's name is a table-name prefix, and every index built on it has to
fit inside Postgres's 63-byte identifier limit. The constant said 32 while the
real ceiling was 22, because the docstring named
``ix_records_c_<name>_index_datetime_lookup`` as the longest identifier and the
longest is in fact the *document* table's
``ix_records_c_<name>_record_type_status_position``. A name of 23 to 32 was
therefore accepted by :func:`sm_records.collections.declare_collection` — which
promises a ``ValueError`` "at import time where there is a person reading a
traceback" — and failed much later, at ``create_all`` or at the host's next
``alembic revision --autogenerate``, with ``IdentifierError``.

Pinning the number alone would fix the number and not the drift, so this file
builds a table set at the limit and one past it and measures what comes out.
An index suffix that grows, or a new one longer than the current worst, fails
here instead of in a host's migration run.

**In a subprocess, for the reason ``test_collections_inert`` gives.**
Declaring a collection puts eight tables on ``Base.metadata`` for the rest of
the process, and this file declares names no test wants: the over-limit one
would make ``create_all`` raise for every test that follows it. It also uses
:func:`sm_records.models._tables._build` for that one, because ``declare`` is
what refuses it — the point of the test is what the refusal is protecting
against.

Nothing here touches a database: every identifier is read off the metadata and
compared against the limit in Python.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

from sm_records.constants import MAX_COLLECTION_NAME_LEN

PG_IDENTIFIER_LIMIT = 63
"""``NAMEDATALEN - 1``. Postgres does not refuse a longer identifier, it
*truncates* it — which is why SQLAlchemy raises ``IdentifierError`` first
rather than letting two indexes silently become one."""

LONGEST_SUFFIX = "_record_type_status_position"
"""The tail of the longest identifier a table set builds, after
``ix_records_c_<name>``. Named so the failure message says what moved."""


def _names(name: str) -> dict[str, list[list]]:
    """Every index and constraint name of the table set called ``name``, with
    its length, gathered in a fresh interpreter."""
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(f"""
            import json
            from sm_records.models import Base
            from sm_records.models._base import collection_prefix
            from sm_records.models._tables import _build

            _build({name!r})
            prefix = collection_prefix({name!r})
            indexes, constraints = [], []
            for table in Base.metadata.tables.values():
                if not table.name.startswith(prefix):
                    continue
                indexes.append([table.name, len(table.name)])
                for index in table.indexes:
                    indexes.append([index.name, len(index.name)])
                for constraint in table.constraints:
                    if constraint.name is not None:
                        constraints.append([str(constraint.name), len(str(constraint.name))])
                for column in table.columns:
                    type_name = getattr(column.type, "name", None)
                    if type_name:
                        indexes.append([type_name, len(type_name)])
            print(json.dumps({{"indexes": indexes, "constraints": constraints}}))
        """),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


def _over_limit(entries: list[list]) -> list[list]:
    return [entry for entry in entries if entry[1] > PG_IDENTIFIER_LIMIT]


def test_a_name_at_the_limit_builds_no_identifier_postgres_would_refuse():
    payload = _names("a" * MAX_COLLECTION_NAME_LEN)
    assert payload["indexes"], "the subprocess built nothing"
    assert _over_limit(payload["indexes"]) == []
    longest = max(payload["indexes"], key=lambda entry: entry[1])
    assert longest[1] == PG_IDENTIFIER_LIMIT, (
        f"the limit is no longer tight: longest is {longest[0]!r} at {longest[1]}"
    )
    assert longest[0].endswith(LONGEST_SUFFIX), (
        f"the longest identifier moved to {longest[0]!r}; update the docstring on "
        "MAX_COLLECTION_NAME_LEN, which names it"
    )


def test_one_character_more_would_not_fit():
    """The other half of "tight": the constant must not be lower than it needs
    to be either, and this is what would fail if a suffix were shortened and
    nobody raised the limit."""
    payload = _names("a" * (MAX_COLLECTION_NAME_LEN + 1))
    assert [entry[0] for entry in _over_limit(payload["indexes"])] == [
        f"ix_records_c_{'a' * (MAX_COLLECTION_NAME_LEN + 1)}{LONGEST_SUFFIX}"
    ]


def test_foreign_key_names_are_over_the_limit_and_that_is_not_what_bounds_the_name():
    """The framework's naming convention spells a foreign key as
    ``fk_<table>_<column>_<referred table>``, which is past 63 for *every*
    collection name there is — ``events`` included — and is hash-truncated by
    SQLAlchemy's identifier preparer at DDL time
    (``fk_records_c_events_index_date_record_id_records_c_even_2956``).

    It is left that way on purpose. Alembic compares foreign keys by their
    column signature rather than by name, and a migration renders the name
    through the same preparer as ``create_all``, so the runtime and the
    migration name the same physical constraint; renaming them now would put
    every existing database out of step with its metadata over a name nothing
    compares. What it costs is one thing, recorded here so it is not
    rediscovered: a hand-written ``DROP CONSTRAINT`` must use the truncated
    spelling ``psql`` shows, not the logical one.
    """
    payload = _names("a" * MAX_COLLECTION_NAME_LEN)
    foreign_keys = [entry for entry in payload["constraints"] if entry[0].startswith("fk_")]
    assert foreign_keys, "the table set declares no foreign keys any more"
    # Every key from an index table back to the document table: the name
    # carries both table names, so it is past the limit for any prefix.
    cascading = [entry for entry in foreign_keys if entry[0].endswith("_record")]
    assert len(cascading) == 7, [entry[0] for entry in cascading]
    assert all(entry[1] > PG_IDENTIFIER_LIMIT for entry in cascading)
    # …and the index names, which are *not* truncated, are what the limit
    # actually has to protect.
    assert _over_limit(payload["indexes"]) == []
