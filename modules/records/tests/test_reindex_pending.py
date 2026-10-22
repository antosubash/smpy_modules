"""``reindex_pending`` markers: a rebuild keeps the ones added while it ran,
and a pending ``unique`` field refuses writes — and says so.

Type keys are unique across the suite on purpose — ``schema.compile``'s model
cache is process-global.
"""

from __future__ import annotations

from types import SimpleNamespace

from simple_module_core.health import HealthStatus
from sm_records.health import stale_reindex_check
from sm_records.models import IndexText, RecordType
from sm_records.services import reindex_runner as runner_mod
from sm_records.services import types as type_service
from sm_records.services.reindex_runner import run_pending
from sm_records.settings import RecordsSettings
from sqlalchemy import select

from tests.app_harness import ADMIN, roles, seed_record, seed_type

API = "/api/records"

T1 = "2026-01-01T00:00:00+00:00"
T2 = "2026-01-02T00:00:00+00:00"


def _field(key: str, type_: str = "text", **cols) -> dict:
    return {"key": key, "type": type_, "label": key.title(), "indexed": True, **cols}


async def _pending(db_state, type_id: int) -> dict:
    async with db_state.session_factory() as session:
        return dict((await session.get(RecordType, type_id)).reindex_pending or {})


async def _indexed_keys(db_state) -> set[str]:
    async with db_state.session_factory() as session:
        return {key for (key,) in (await session.execute(select(IndexText.field_key))).all()}


# --- a rebuild must not erase a marker enqueued while it ran ------------


async def test_a_marker_added_during_a_rebuild_is_not_erased_by_it(db_state, monkeypatch):
    """The runner used to assign ``reindex_pending`` back from the snapshot it
    took at the start, so a schema change committed mid-rebuild lost its
    marker — and its rows were never written either, because the runner held
    the fields as they were before it. Nothing would ever rebuild ``b``."""
    rtype = await seed_type(db_state, "r2race", [_field("name"), _field("a")], display_field="name")
    for i in range(3):
        await seed_record(db_state, rtype, {"name": f"n{i}", "a": str(i), "b": f"bb{i}"})
    async with db_state.session_factory() as session:
        row = await session.get(RecordType, rtype.id)
        row.reindex_pending = {"a": T1}
        session.add(row)
        await session.commit()

    async def commit_a_second_change() -> None:
        async with db_state.session_factory() as session:
            row = await session.get(RecordType, rtype.id)
            row.fields = [_field("name"), _field("a"), _field("b")]
            row.schema_version += 1
            row.version += 1
            row.reindex_pending = {**dict(row.reindex_pending or {}), "b": T2}
            session.add(row)
            await session.commit()

    # Between two of the run's transactions: each opens with the type lock
    # (#82), so a change can only commit in the gap before the next one —
    # here, before the lock that follows the first batch's commit.
    real, calls = runner_mod.lock_type, []

    async def racing(db, rtype_):
        calls.append(True)
        if len(calls) == 2:
            await commit_a_second_change()
        await real(db, rtype_)

    monkeypatch.setattr(runner_mod, "lock_type", racing)
    await run_pending(db_state, rtype.id, settings=RecordsSettings())

    # The fields moved underneath this run, so it clears nothing at all: what
    # it rebuilt was the old shape. Both markers are left for the next run.
    assert await _pending(db_state, rtype.id) == {"a": T1, "b": T2}
    assert "b" not in await _indexed_keys(db_state)

    monkeypatch.undo()
    await run_pending(db_state, rtype.id, settings=RecordsSettings())
    assert await _pending(db_state, rtype.id) == {}
    assert "b" in await _indexed_keys(db_state)


# --- a pending unique field refuses the write, and says so --------------


async def test_a_write_against_a_pending_unique_field_is_the_intended_conflict(client):
    """``count_query`` raises while it is *built*, so the ``Conflict`` that
    explains the refusal was unreachable and the caller got the query
    grammar's error about a filter it never wrote."""
    rtype = await seed_type(
        client.db_state, "r2uniq", [_field("name", unique=True)], display_field="name"
    )
    await seed_record(client.db_state, rtype, {"name": "a"})
    async with client.db_state.session_factory() as session:
        row = await session.get(RecordType, rtype.id)
        row.reindex_pending = {"name": T1}
        session.add(row)
        await session.commit()

    resp = await client.post(
        f"{API}/types/r2uniq/records", json={"data": {"name": "b"}}, headers=roles(ADMIN)
    )
    assert resp.status_code == 409, resp.text
    assert "'name' is being reindexed" in resp.json()["detail"]
    assert "uniqueness cannot be checked" in resp.json()["detail"]


async def test_the_health_detail_says_that_writes_are_refused(db, db_state):
    """A stale marker on a ``unique`` field is not a slow filter — it is a
    type nobody can write to until the rebuild runs."""
    rtype = await type_service.create_type(
        db,
        key="r2health",
        label="Health",
        fields_raw=[_field("code", unique=True)],
        settings=RecordsSettings(),
    )
    rtype.reindex_pending = {"code": "2020-01-01T00:00:00+00:00"}
    db.add(rtype)
    await db.commit()

    module = SimpleNamespace(db=db_state, settings=RecordsSettings())
    result = await stale_reindex_check(module).check()
    assert result.status is HealthStatus.DEGRADED
    assert "writes to this type are refused" in result.detail
