"""The collections every collection test runs against — declared at import.

Phase 5 §6.1 makes declaration *code* that runs before the app is built, and
:func:`sm_records.models._tables.seal` closes the registry as soon as a
``RecordsModule`` registers its settings. Pytest imports every test module
during collection, before it runs a single test, so declaring here — at module
scope of a module the collection tests import — is the only place that is
reliably "before the app". A ``declare_collection`` inside a fixture would
race the first API test in the session.

Two collections rather than one, deliberately. ``events`` mirrors the demo
host, so the seeder's ``event`` type is exercised by the same names it will
have in production. ``archive`` exists so that anything keyed by a record's
*id* has two collections to confuse: two collections number their records
independently, so ``(collection, id)`` is the identity and a test with one
collection cannot tell a correct implementation from an id-keyed one.

Declaring them makes ``Base.metadata`` hold sixteen more tables **for the
whole session**, which is why the inert-when-unused property of §6.5 is
asserted in a subprocess instead (``test_collections_inert.py``).
"""

from __future__ import annotations

from typing import Any

from sm_records.collections import declare_collection
from sm_records.models import tables_for

EVENTS = declare_collection("events")
ARCHIVE = declare_collection("archive")

COLLECTION_NAMES = ("archive", "events")
"""Sorted, as ``collections()`` returns them."""


async def make_collection_record(db: Any, rtype: Any, data: dict, **cols: Any) -> Any:
    """``conftest.create_record``, against the type's own table set.

    The fixture in ``conftest`` instantiates the global ``Record`` class by
    name, which is right for every test that predates collections and wrong
    for one whose type lives in a collection — the row would go in the shared
    table and every read through ``tables_for`` would miss it.
    """
    record = tables_for(rtype).record(
        type_id=rtype.id,
        data=data,
        schema_version=cols.pop("schema_version", rtype.schema_version),
        **cols,
    )
    db.add(record)
    await db.flush()
    return record


async def seed_collection_record(db_state: Any, rtype: Any, data: dict, **cols: Any) -> Any:
    """``app_harness.seed_record`` against the type's own table set, committed
    on its own session so a request through the client sees it."""
    async with db_state.session_factory() as session:
        record = await make_collection_record(session, rtype, data, **cols)
        await session.commit()
        await session.refresh(record)
        return record
