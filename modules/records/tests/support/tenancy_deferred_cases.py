"""Shared setup for test_tenancy_deferred."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from simple_module_db.listeners import current_tenant_id
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import install_guard, tenant_scope
from sm_records.models import IndexNumber, RecordType
from sm_records.records import deferred
from sm_records.records.services import preview_jobs, schema_change
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service
from sqlalchemy import select
from starlette.requests import Request

SETTINGS = RecordsSettings()


@pytest.fixture
def guarded(db_state):
    install_guard(db_state.sync_session_class)
    return db_state


def _app(db_state: Any) -> Any:
    """``request.app`` as the deferred callers reach it: ``state.sm.db``."""
    return SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(db=db_state)))


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


async def _call(fn, *args) -> None:
    """``work`` for :func:`_serve` out of a plain function."""
    fn(*args)


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
