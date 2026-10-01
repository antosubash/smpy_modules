"""Inert when unused — §6.5, which the design calls the acceptance test.

"With no ``declare_collection`` call the module's metadata is byte-identical
to Phase 4's, no migration is generated, and ``tables_for`` always returns the
global set."

**In a subprocess, and it has to be.** Declaration is a process-global side
effect, and ``tests/collections_harness.py`` declares two collections at
import time for every other file in this directory — so by the time anything
here runs, this process is no longer a process that declares none. The only
honest way to assert what a *fresh* interpreter sees is to start one.

The literal table list below is therefore the real assertion: not "the same as
whatever is loaded", which would be vacuous, but the eleven names Phase 4
shipped, written out. A collection table appearing in a default import — or a
global table quietly renamed — fails here and nowhere else.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

PHASE_4_TABLES = [
    "records_index_bool",
    "records_index_date",
    "records_index_datetime",
    "records_index_number",
    "records_index_reduce",
    "records_index_ref",
    "records_index_text",
    "records_record",
    "records_revision",
    "records_type",
    "records_type_revision",
]
"""Every table the module owned before Phase 5 §6, sorted. The reduce table of
§5 is the eleventh and the newest; nothing else has moved since Phase 4."""


def _run(source: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_fresh_import_declares_no_collection_and_owns_exactly_the_phase_4_tables():
    out = _run("""
        import json
        from sm_records.models import Base
        from sm_records.collections import collections
        print(json.dumps({
            "tables": sorted(Base.metadata.tables),
            "collections": list(collections()),
        }))
    """)
    import json

    payload = json.loads(out)
    assert payload["collections"] == []
    assert payload["tables"] == PHASE_4_TABLES


def test_tables_for_answers_with_the_global_set_for_every_type_in_a_fresh_import():
    """Including a type whose ``collection`` is ``None`` — which is every type
    on such a host, because ``TypeCreate`` refuses any other value there."""
    out = _run("""
        from sm_records.models import GLOBAL, RecordType, tables_for
        rtype = RecordType(key="a", label="A", label_plural="As")
        print(tables_for(rtype) is GLOBAL)
    """)
    assert out == "True"


def test_importing_the_collections_module_declares_nothing_on_its_own():
    """The module is the front door, not a declaration: a host that imports it
    without calling ``declare_collection`` still runs the Phase 4 code paths
    against the Phase 4 tables."""
    out = _run("""
        import json
        import sm_records.collections  # noqa: F401
        from sm_records.models import Base
        print(json.dumps(sorted(Base.metadata.tables)))
    """)
    import json

    assert json.loads(out) == PHASE_4_TABLES


def test_the_declared_metadata_is_exactly_the_phase_4_tables_plus_the_collections():
    """The other half of the property, in *this* process: declaring adds eight
    tables per collection and changes nothing about the eleven."""
    from sm_records.models import Base

    from tests.collections_harness import COLLECTION_NAMES

    names = sorted(Base.metadata.tables)
    assert [n for n in names if not n.startswith("records_c_")] == PHASE_4_TABLES
    for collection in COLLECTION_NAMES:
        owned = [n for n in names if n.startswith(f"records_c_{collection}_")]
        assert len(owned) == 8, owned
