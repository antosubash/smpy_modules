"""Work that runs after the request that asked for it: tenancy design §A.5, K4.

``DeferredJobsMiddleware`` drains its queue *outside* ``TenantMiddleware`` and
records' own binding, so by the time a job runs, the tenant of the request
that queued it is gone (FACT 2″). These tests use that production shape: an
inner app binds a tenant, the way a records router would, and the real drain
wraps it. No HTTP is involved, because request binding is Phase 3's. Each
test opts out of the suite's ``default`` binding, since the question is what
the drain sees with nothing bound around it.

The guard is installed on every database here. An ORM read or write that ran
unbound would raise ``TenantUnbound``, not quietly see every tenant's rows.
"""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from typing import Any

import pytest
from simple_module_core.events import EventBus
from simple_module_db.listeners import TenantIsolationError, current_tenant_id
from sm_records import deferred, events
from sm_records.contracts.events import RecordCreated, RecordTypeDeleted
from sm_records.endpoints.api.preview import read_preview_job
from sm_records.endpoints.api.types import _schedule_reindex_if_pending
from sm_records.models import IndexNumber, Record, RecordType
from sm_records.services import preview_jobs, schema_change
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services.errors import NotFound
from sm_records.services.preview_runner import run_preview_job
from sm_records.services.reindex_runner import pending_type_ids, run_pending
from sm_records.settings import RecordsSettings
from sm_records.tenancy import TenantUnbound, install_guard, tenant_scope
from sqlalchemy import select
from starlette.requests import Request

pytestmark = pytest.mark.unbound_tenant

SETTINGS = RecordsSettings()


@pytest.fixture
def guarded(db_state):
    install_guard(db_state.sync_session_class)
    return db_state


def _app(db_state: Any, bus: Any = None) -> Any:
    """``request.app`` as the deferred callers reach it: ``state.sm.{db,event_bus}``."""
    return SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=db_state, event_bus=bus)))


async def _serve(app: Any, tenant: str, work) -> None:
    """One request: ``work(request)`` runs bound to ``tenant``, and the drain
    runs after the binding is gone. This is the production order."""

    async def inner(scope, receive, send):
        with tenant_scope(tenant):
            await work(Request(scope))

    scope = {"type": "http", "app": app, "method": "POST", "path": "/", "headers": []}
    await deferred.DeferredJobsMiddleware(inner)(scope, None, None)
    assert current_tenant_id.get() is None


async def _product(db_state: Any, tenant: str, field_def) -> RecordType:
    """A ``product`` type in ``tenant`` with one record, retyped text → number,
    so its ``price`` index is pending, exactly as a ``PUT /types/product`` leaves it."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as session:
            rtype = await type_service.create_type(
                session,
                key="product",
                label="Product",
                fields_raw=[field_def("price", "text")],
                settings=SETTINGS,
            )
            await record_service.create_record(
                session, rtype, data={"price": "12"}, settings=SETTINGS
            )
            rtype, _ = await schema_change.apply(
                session,
                rtype,
                fields_raw=[field_def("price", "number")],
                expected_version=1,
                settings=SETTINGS,
            )
            await session.commit()
            assert rtype.reindex_pending, "the retype should have left a marker"
            return rtype


async def _state(db_state: Any, tenant: str) -> tuple[dict, int]:
    """``(reindex_pending, number index rows)`` of ``tenant``'s ``product``."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as session:
            rtype = (await session.execute(select(RecordType))).scalars().one()
            rows = (
                await session.execute(select(IndexNumber).where(IndexNumber.type_id == rtype.id))
            ).all()
            return dict(rtype.reindex_pending or {}), len(rows)


# --- defer() -----------------------------------------------------------------


async def _call(fn, *args) -> None:
    """``work`` for :func:`_serve` out of a plain function."""
    fn(*args)


async def test_a_job_runs_in_the_tenant_that_queued_it():
    seen: list[str | None] = []

    async def job() -> None:
        seen.append(current_tenant_id.get())

    await _serve(_app(None), "acme", lambda request: _call(deferred.defer, request, job))
    assert seen == ["acme"]


async def test_queuing_with_no_tenant_bound_is_refused_at_once():
    scope = {"type": "http", "app": _app(None), deferred.SCOPE_KEY: []}

    async def job() -> None:  # pragma: no cover - must never be queued
        raise AssertionError

    with pytest.raises(TenantUnbound):
        deferred.defer(Request(scope), job)
    assert scope[deferred.SCOPE_KEY] == []


async def test_the_detached_fallback_runs_in_the_captured_tenant_too():
    seen: list[str | None] = []

    async def job() -> None:
        seen.append(current_tenant_id.get())

    scope = {"type": "http", "app": _app(None)}  # no drain installed
    before = set(deferred._orphans)
    with tenant_scope("acme"):
        deferred.defer(Request(scope), job)
    [task] = set(deferred._orphans) - before
    await task
    assert seen == ["acme"]


# --- the reindex a type write queues --------------------------------------------


async def test_a_type_write_in_acme_reindexes_in_acme(guarded, field_def):
    acme = await _product(guarded, "acme", field_def)
    await _product(guarded, "globex", field_def)  # same key, its own marker
    assert await _state(guarded, "acme") == (acme.reindex_pending, 0)

    await _serve(
        _app(guarded),
        "acme",
        lambda request: _call(_schedule_reindex_if_pending, request, acme, SETTINGS),
    )

    pending, rows = await _state(guarded, "acme")
    assert (pending, rows) == ({}, 1)
    untouched, none = await _state(guarded, "globex")
    assert untouched and none == 0, "globex's same-key type is not acme's to rebuild"


async def test_the_runner_binds_the_types_tenant_and_refuses_another(guarded, field_def):
    acme = await _product(guarded, "acme", field_def)
    globex = await _product(guarded, "globex", field_def)
    async with guarded.session_factory() as session:
        assert await pending_type_ids(session) == sorted([acme.id, globex.id])

    with tenant_scope("globex"), pytest.raises(TenantIsolationError):
        await run_pending(guarded, acme.id, settings=SETTINGS)
    assert (await _state(guarded, "acme"))[1] == 0

    # Unbound, as the CLI calls it: the runner binds the row's own tenant.
    assert await run_pending(guarded, acme.id, settings=SETTINGS) == 1
    assert await _state(guarded, "acme") == ({}, 1)


# --- events ------------------------------------------------------------------


async def test_events_carry_the_tenant_and_the_subscriber_runs_bound(guarded, field_def):
    acme = await _product(guarded, "acme", field_def)
    await _product(guarded, "globex", field_def)
    with tenant_scope("acme"):
        async with guarded.session_factory() as session:
            record = (await session.execute(select(Record))).scalars().one()

    seen: list[tuple[Any, str | None, int]] = []

    async def subscriber(event: Any) -> None:
        # Read back through the ORM, as a real handler would. Bound, the
        # filter shows acme's rows only. Unbound, the guard would raise.
        async with guarded.session_factory() as session:
            found = (await session.execute(select(Record))).scalars().all()
        seen.append((event, current_tenant_id.get(), len(found)))

    bus = EventBus()
    bus.subscribe(RecordCreated, subscriber)
    bus.subscribe(RecordTypeDeleted, subscriber)

    async def publish(request: Request) -> None:
        events.publish(
            request,
            events.created(acme, record),
            *events.type_deleted("product", [record]),
        )

    await _serve(_app(guarded, bus), "acme", publish)

    assert [(type(e).__name__, e.tenant_id, bound, n) for e, bound, n in seen] == [
        ("RecordCreated", "acme", "acme", 1),
        ("RecordTypeDeleted", "acme", "acme", 1),
    ]


# --- schema preview jobs -----------------------------------------------------------


async def _types(db_state: Any) -> dict[str, RecordType]:
    out = {}
    for tenant in ("acme", "globex"):
        with tenant_scope(tenant):
            async with db_state.session_factory() as session:
                out[tenant] = (await session.execute(select(RecordType))).scalars().one()
    return out


def _job(rtype: RecordType) -> preview_jobs.PreviewJob:
    return preview_jobs.start(
        tenant_id=rtype.tenant_id,
        type_key=rtype.key,
        type_id=rtype.id,
        type_version=rtype.version,
        signature="sig",
        total=1,
        ttl_seconds=600,
    )


async def test_a_preview_job_is_a_404_under_another_tenants_same_key(guarded, field_def):
    await _product(guarded, "acme", field_def)
    await _product(guarded, "globex", field_def)
    types = await _types(guarded)
    job = _job(types["acme"])

    with tenant_scope("acme"):
        assert (await read_preview_job(job.id, rtype=types["acme"])).status == "running"
    with tenant_scope("globex"), pytest.raises(NotFound):
        await read_preview_job(job.id, rtype=types["globex"])
    assert job.tenant_id == "acme" and job.type_id == types["acme"].id


async def test_the_preview_runner_binds_the_jobs_tenant(guarded, field_def):
    await _product(guarded, "acme", field_def)
    with tenant_scope("acme"):
        async with guarded.session_factory() as session:
            acme = (await session.execute(select(RecordType))).scalars().one()
    run = partial(
        run_preview_job, guarded, fields=[dict(f) for f in acme.fields], settings=SETTINGS
    )

    done = _job(acme)
    await run(done.id, acme.id)
    assert (done.status, done.error, done.checked) == ("done", None, 1)

    refused = _job(acme)
    with tenant_scope("globex"):
        await run(refused.id, acme.id)
    assert refused.status == "failed" and "cannot bind tenant 'acme'" in (refused.error or "")
