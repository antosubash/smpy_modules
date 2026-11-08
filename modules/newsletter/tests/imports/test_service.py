"""Reading, mapping, queueing and discarding an import; the list wrapper."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_newsletter.core import errors_import
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.imports import service
from sm_newsletter.imports.lists import create_list
from sm_newsletter.models import ImportEntry, ImportJob
from sm_records.contracts.newsletter_import import importable_fields
from sqlalchemy import func, select

from tests.imports.world import FIELDS, job_of, staged, upload
from tests.support.app import build_app
from tests.support.import_world import SUB, set_job
from tests.support.records_seed import restrict_list, seed_list

pytestmark = pytest.mark.unbound_tenant


@pytest_asyncio.fixture
async def world():
    app, state = await build_app()
    await seed_list(state, "default", fields=FIELDS)
    yield app, state
    await state.engine.dispose()


async def _staged(state, tenant="default"):
    return await staged(state, upload(SUB, [["a@x.org", "Ada", "L", "VIP"]]), tenant=tenant)


async def test_get_import_other_tenant_is_404(world):
    _, state = world
    jid = await _staged(state)
    await seed_list(state, "other", fields=FIELDS)
    with tenant_scope("other"):
        async with state.session_factory() as s:
            with pytest.raises(NotFound):
                await service.get_import(s, tenant_id="other", import_id=jid, roles=None)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            got = await service.get_import(s, tenant_id="default", import_id=jid, roles=None)
            assert got.id == jid


async def test_restricted_list_import_is_404(world):
    _, state = world
    jid = await _staged(state)
    await restrict_list(state, "default", "news", ["admin"])
    with tenant_scope("default"):
        async with state.session_factory() as s:
            with pytest.raises(NotFound):
                await service.get_import(s, tenant_id="default", import_id=jid, roles=["editor"])
            assert await service.list_imports(s, tenant_id="default", roles=["editor"]) == []
            got = await service.get_import(s, tenant_id="default", import_id=jid, roles=["admin"])
            assert got.id == jid


async def test_list_imports_newest_first(world):
    _, state = world
    first, second = await _staged(state), await _staged(state)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            got = await service.list_imports(s, tenant_id="default", roles=None)
            assert [j.id for j in got] == [second, first]
            assert len(await service.list_imports(s, tenant_id="default", roles=None, limit=1)) == 1


async def test_set_mapping_only_while_staged(world):
    _, state = world
    jid = await _staged(state)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            targets = await importable_fields(s, tenant_id="default", type_key="news")
            got = await service.set_mapping(
                s, tenant_id="default", job=await s.get(ImportJob, jid),
                raw={"fields": {"0": "last_name"}, "tags": False}, targets=targets,
            )  # fmt: skip
            assert got.mapping == {"fields": {"0": "last_name"}, "tags": False}
            with pytest.raises(errors_import.ImportBadMapping):
                await service.set_mapping(
                    s,
                    tenant_id="default",
                    job=got,
                    raw={"fields": {"9": "last_name"}},
                    targets=targets,
                )
            await s.commit()
    assert (await job_of(state, jid)).mapping == {"fields": {"0": "last_name"}, "tags": False}
    await set_job(state, jid, status="queued")
    with tenant_scope("default"):
        async with state.session_factory() as s:
            with pytest.raises(errors_import.ImportNotStaged):
                await service.set_mapping(
                    s, tenant_id="default", job=await s.get(ImportJob, jid), raw={}, targets=targets
                )
    assert (await job_of(state, jid)).mapping == {"fields": {"0": "last_name"}, "tags": False}


@pytest.mark.parametrize(
    ("status", "ok"),
    [("staged", True), ("failed", True), ("queued", False), ("running", False), ("done", False)],
)
async def test_queue_apply_only_from_staged_or_failed(world, status, ok):
    _, state = world
    jid = await _staged(state)
    await set_job(state, jid, status=status)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            job = await s.get(ImportJob, jid)
            if ok:
                got = await service.queue_apply(s, tenant_id="default", job=job)
                assert got.status == "queued"
            else:
                with pytest.raises(errors_import.ImportNotStaged):
                    await service.queue_apply(s, tenant_id="default", job=job)
            await s.commit()
    assert (await job_of(state, jid)).status == ("queued" if ok else status)


async def test_queue_apply_is_conditional_on_the_stored_status(world):
    """The object says staged, the row has moved on: nothing is queued twice."""
    _, state = world
    jid = await _staged(state)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            job = await s.get(ImportJob, jid)
            await set_job(state, jid, status="running")
            with pytest.raises(errors_import.ImportNotStaged):
                await service.queue_apply(s, tenant_id="default", job=job)


async def _counts(state):
    with tenant_scope("default"):
        async with state.session_factory() as s:
            jobs = (await s.execute(select(func.count()).select_from(ImportJob))).scalar_one()
            rows = (await s.execute(select(func.count()).select_from(ImportEntry))).scalar_one()
            return jobs, rows


@pytest.mark.parametrize("status", ["staged", "done", "failed"])
async def test_discard_deletes_rows(world, status):
    _, state = world
    jid = await _staged(state)
    await set_job(state, jid, status=status)
    assert await _counts(state) == (1, 1)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            await service.discard(s, tenant_id="default", job=await s.get(ImportJob, jid))
            await s.commit()
    assert await _counts(state) == (0, 0)


async def test_a_discarded_import_id_is_never_handed_out_again(world):
    """A stale ``?id=`` tab must not reach a newer import (SQLite ``AUTOINCREMENT``)."""
    _, state = world
    jid = await _staged(state)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            await service.discard(s, tenant_id="default", job=await s.get(ImportJob, jid))
            await s.commit()
    assert await _staged(state) != jid


async def test_discard_expected_status_mismatch_keeps_import(world):
    _, state = world
    jid = await _staged(state)
    await set_job(state, jid, status="done")
    with tenant_scope("default"):
        async with state.session_factory() as s:
            with pytest.raises(errors_import.ImportNotStaged):
                await service.discard(
                    s,
                    tenant_id="default",
                    job=await s.get(ImportJob, jid),
                    expected_status="staged",
                )
    assert await _counts(state) == (1, 1)


@pytest.mark.parametrize("status", ["queued", "running"])
async def test_discard_running_refused(world, status):
    _, state = world
    jid = await _staged(state)
    await set_job(state, jid, status=status)
    with tenant_scope("default"):
        async with state.session_factory() as s:
            with pytest.raises(errors_import.ImportRunning):
                await service.discard(s, tenant_id="default", job=await s.get(ImportJob, jid))
    assert await _counts(state) == (1, 1)


async def test_create_list_maps_errors(world):
    app, state = world
    with tenant_scope("default"):
        async with state.session_factory() as s:
            key = await create_list(app, s, tenant_id="default", key="fresh", label="Fresh")
            assert key == "fresh"
            await s.commit()
        async with state.session_factory() as s:
            with pytest.raises(errors_import.ListExists):
                await create_list(app, s, tenant_id="default", key="fresh", label="Again")
            with pytest.raises(errors_import.InvalidListKey):
                await create_list(app, s, tenant_id="default", key="Not A Key!", label="X")
