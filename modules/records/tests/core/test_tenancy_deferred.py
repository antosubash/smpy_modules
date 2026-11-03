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

import pytest
from simple_module_db.listeners import current_tenant_id
from sm_records.core.tenancy import TenantUnbound, tenant_scope
from sm_records.records import deferred
from sm_records.web.endpoints.api._type_writes import _schedule_reindex_if_pending
from starlette.requests import Request

from tests.support.tenancy_deferred_cases import (
    SETTINGS,
    _app,
    _call,
    _product,
    _serve,
    _state,
)
from tests.support.tenancy_deferred_cases import guarded as guarded

pytestmark = pytest.mark.unbound_tenant


# --- defer() -----------------------------------------------------------------


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


# --- events ------------------------------------------------------------------


# --- schema preview jobs -----------------------------------------------------------
