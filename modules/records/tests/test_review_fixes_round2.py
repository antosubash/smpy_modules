"""Regressions for the second review pass — every test here failed before its
fix, and each one is named after the finding it pins.

The shape they share is a *second* actor: a schema change committed while a
rebuild runs, values written under a definition that has since changed, a
revision taken before a field went away. Type keys are unique across the
suite on purpose — ``schema.compile``'s model cache is process-global.
"""

from __future__ import annotations

from types import SimpleNamespace

from simple_module_core.health import HealthStatus
from sm_records.health import stale_reindex_check
from sm_records.index import reindex as reindex_mod
from sm_records.models import IndexText, RecordType
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


# --- F1: a rebuild must not erase a marker enqueued while it ran ------------


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

    # Wrapped at the batch, which is the unit the rebuild writes in.
    real, raced = reindex_mod.reindex_batch, []

    async def racing(db, records, rtype_, **kwargs):
        out = await real(db, records, rtype_, **kwargs)
        if not raced:
            raced.append(True)
            await commit_a_second_change()
        return out

    monkeypatch.setattr(reindex_mod, "reindex_batch", racing)
    await run_pending(db_state, rtype.id, settings=RecordsSettings())

    # The fields moved underneath this run, so it clears nothing at all: what
    # it rebuilt was the old shape. Both markers are left for the next run.
    assert await _pending(db_state, rtype.id) == {"a": T1, "b": T2}
    assert "b" not in await _indexed_keys(db_state)

    monkeypatch.undo()
    await run_pending(db_state, rtype.id, settings=RecordsSettings())
    assert await _pending(db_state, rtype.id) == {}
    assert "b" in await _indexed_keys(db_state)


# --- F2: orphaned values are dry-run before they are restored (§8.8) --------


async def test_restoring_orphaned_values_reports_the_ones_that_do_not_validate(client):
    """Re-adding a deleted key is classified ADDITIVE, so nothing scanned the
    values that key still holds — and ``restore`` claimed ``failing=0`` while
    handing back ``"oops"`` as a ``number``."""
    rtype = await seed_type(
        client.db_state, "r2orph", [_field("name"), _field("price")], display_field="name"
    )
    for i, price in enumerate(["12", "oops", "nope"]):
        await seed_record(client.db_state, rtype, {"name": f"n{i}", "price": price})

    resp = await client.put(
        f"{API}/types/r2orph",
        json={"expected_version": 1, "fields": [_field("name")]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text

    new_fields = [_field("name"), _field("price", "number")]
    resp = await client.post(
        f"{API}/types/r2orph/schema/preview", json={"fields": new_fields}, headers=roles(ADMIN)
    )
    report = resp.json()["report"]
    assert report == {**report, "checked": 3, "failing": 2}
    assert report["orphaned_conflicts"] == {"price": 3}
    assert report["sample"][0]["errors"] == [{"field": "price", "message": "not a number"}]

    body = {"expected_version": 2, "fields": new_fields, "orphaned": "restore"}
    resp = await client.put(f"{API}/types/r2orph", json=body, headers=roles(ADMIN))
    assert resp.status_code == 409, resp.text
    assert resp.json()["report"]["failing"] == 2

    resp = await client.put(
        f"{API}/types/r2orph", json={**body, "force": True}, headers=roles(ADMIN)
    )
    assert resp.status_code == 200, resp.text
    items = (await client.get(f"{API}/types/r2orph/records", headers=roles(ADMIN))).json()["items"]
    marked = 0
    for item in items:
        url = f"{API}/types/r2orph/records/{item['uuid']}"
        marked += bool((await client.get(url, headers=roles(ADMIN))).json()["invalid"])
    assert marked == 2


# --- F3: a revision older than a field deletion is still restorable ---------


async def test_restoring_a_revision_taken_before_a_field_was_deleted(client):
    """The snapshot still carries the deleted key at top level and the
    compiled validator is ``extra="forbid"``, which made every such restore a
    permanent 422. The undeclared half goes under ``_orphaned`` instead."""
    await seed_type(
        client.db_state, "r2rev", [_field("name"), _field("note")], display_field="name"
    )
    created = await client.post(
        f"{API}/types/r2rev/records",
        json={"data": {"name": "a", "note": "keep me"}},
        headers=roles(ADMIN),
    )
    uuid = created.json()["uuid"]
    resp = await client.put(
        f"{API}/types/r2rev/records/{uuid}",
        json={"expected_version": 1, "data": {"name": "b", "note": "later"}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    revisions = (
        await client.get(f"{API}/types/r2rev/records/{uuid}/revisions", headers=roles(ADMIN))
    ).json()["items"]
    first = next(item for item in revisions if item["version"] == 1)

    resp = await client.put(
        f"{API}/types/r2rev",
        json={"expected_version": 1, "fields": [_field("name")]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        f"{API}/types/r2rev/records/{uuid}/revisions/{first['id']}/restore",
        json={"expected_version": 2},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    # Nothing from the revision is dropped: ``name`` is the write, ``note`` is
    # recovery data — and it is the *revision's* value, not the later edit's.
    assert resp.json()["data"] == {"name": "a", "_orphaned": {"note": "keep me"}}
    events = [
        item["event"]
        for item in (
            await client.get(f"{API}/types/r2rev/records/{uuid}/revisions", headers=roles(ADMIN))
        ).json()["items"]
    ]
    assert events[0] == "restore"


# --- F7: a list page reads its rows but does not validate them --------------


async def test_a_list_does_not_validate_its_rows_but_a_single_read_does(client):
    """``read_view`` ran the compiled validator per record, for a badge only
    the editor shows — fifty pydantic passes per page."""
    rtype = await seed_type(client.db_state, "r2list", [_field("price")], slug_field=None)
    await seed_record(client.db_state, rtype, {"price": "oops"})
    resp = await client.put(
        f"{API}/types/r2list",
        json={"expected_version": 1, "fields": [_field("price", "number")], "force": True},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text

    listed = (await client.get(f"{API}/types/r2list/records", headers=roles(ADMIN))).json()["items"]
    assert [item["invalid"] for item in listed] == [[]]
    assert listed[0]["data"] == {"price": "oops"}

    single = await client.get(
        f"{API}/types/r2list/records/{listed[0]['uuid']}", headers=roles(ADMIN)
    )
    assert single.json()["invalid"] == [{"field": "price", "message": "not a number"}]


# --- F8: a pending unique field refuses the write, and says so --------------


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


# --- F9: a no-op schema change is not a schema change -----------------------


async def test_a_rollback_to_the_current_schema_only_bumps_the_version(client):
    """``apply`` bumped ``schema_version`` whenever ``fields`` was passed at
    all, and ``rollback`` always passes it — so undoing to where you already
    are marked every record stale and snapshotted a duplicate revision."""
    fields = [_field("name")]
    created = await client.post(
        f"{API}/types",
        json={"key": "r2noop", "label": "Noop", "fields": fields, "display_field": "name"},
        headers=roles(ADMIN),
    )
    assert created.status_code == 201, created.text
    await client.post(
        f"{API}/types/r2noop/records", json={"data": {"name": "a"}}, headers=roles(ADMIN)
    )
    before = (await client.get(f"{API}/types/r2noop", headers=roles(ADMIN))).json()
    revisions = (await client.get(f"{API}/types/r2noop/revisions", headers=roles(ADMIN))).json()

    resp = await client.post(
        f"{API}/types/r2noop/revisions/1/restore",
        json={"expected_version": before["version"]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["schema_version"] == before["schema_version"]
    assert resp.json()["version"] == before["version"] + 1
    assert resp.json()["reindex_pending"] == {}

    after = (await client.get(f"{API}/types/r2noop/revisions", headers=roles(ADMIN))).json()
    assert len(after["items"]) == len(revisions["items"])
    listed = (await client.get(f"{API}/types/r2noop/records", headers=roles(ADMIN))).json()["items"]
    assert [item["schema_stale"] for item in listed] == [False]
