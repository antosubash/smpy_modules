"""test_tenancy_deferred cases."""

from __future__ import annotations
from functools import partial
from types import SimpleNamespace
from typing import Any
import pytest
from simple_module_core.events import EventBus
from simple_module_db.listeners import TenantIsolationError, current_tenant_id
from sm_records.records import deferred
from sm_records.core import events
from sm_records.contracts.events import RecordCreated, RecordTypeDeleted
from sm_records.web.endpoints.api.preview import read_preview_job
from sm_records.web.endpoints.api.types import _schedule_reindex_if_pending
from sm_records.models import IndexNumber, Record, RecordType
from sm_records.records.services import preview_jobs, schema_change
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service
from sm_records.records.services.errors import NotFound
from sm_records.records.services.preview_runner import run_preview_job
from sm_records.records.services.reindex_runner import pending_type_ids, run_pending
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import TenantUnbound, install_guard, tenant_scope
from sqlalchemy import select
from starlette.requests import Request
from tests.support.tenancy_deferred_cases import guarded, _app, _serve, _product, _state, _call, _types, _job, SETTINGS

pytestmark = pytest.mark.unbound_tenant


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

    # Queued bound to acme, committed with nothing bound — the shape of a
    # callback that runs after the request's own binding has gone.
    async with guarded.session_factory() as session:
        events.attach(session, bus)
        with tenant_scope("acme"):
            events.emit(
                session,
                events.created(acme, record),
                *events.type_deleted("product", [record]),
            )
        assert current_tenant_id.get() is None
        await events.commit(session)

    assert [(type(e).__name__, e.tenant_id, bound, n) for e, bound, n in seen] == [
        ("RecordCreated", "acme", "acme", 1),
        ("RecordTypeDeleted", "acme", "acme", 1),
    ]


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
