"""Suppression rows, lifts and purged subscribers for the suppression-admin tests.

Each helper opens a session of its own bound to the tenant it is given and
commits, so what it wrote is what a later session reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sm_newsletter.core.suppression import suppress
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Suppression, SuppressionLift
from sqlalchemy import select


async def seed_row(
    db_state: Any,
    tenant: str,
    email: str,
    reason: str,
    *,
    key: str = "",
    at: datetime | None = None,
    source: str = "send",
) -> None:
    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            await suppress(
                s,
                tenant_id=tenant,
                email=email,
                reason=reason,
                source=source,
                list_type_key=key,
                now=at,
            )
            await finalize_session(s)


async def rows(db_state: Any, tenant: str = "default") -> list[Suppression]:
    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            stmt = select(Suppression).where(Suppression.tenant_id == tenant)
            return list((await s.execute(stmt.order_by(Suppression.id))).scalars())


async def lifts(db_state: Any, tenant: str = "default") -> list[SuppressionLift]:
    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            stmt = select(SuppressionLift).where(SuppressionLift.tenant_id == tenant)
            return list((await s.execute(stmt.order_by(SuppressionLift.id))).scalars())


async def purge(db_state: Any, tenant: str, uuid: str, key: str = "news") -> None:
    """Trash and purge a subscriber through records' services (test-only)."""
    from sm_records.core import events
    from sm_records.core.settings import RecordsSettings
    from sm_records.core.tenancy import tenant_scope as records_scope
    from sm_records.records.services import records as record_service
    from sm_records.records.services import types as type_service

    settings = RecordsSettings()
    with records_scope(tenant):
        async with db_state.session_factory() as db:
            rtype = await type_service.get_type(db, key)
            record = await record_service.get_record(db, rtype, uuid)
            await record_service.soft_delete_record(db, rtype, record, settings=settings)
            await record_service.hard_delete_record(db, rtype, record)
            await events.commit(db)


async def status_of(db_state: Any, tenant: str, uuid: str, key: str = "news") -> str:
    from sm_records.contracts.newsletter import subscribers_by_uuid

    with tenant_scope(tenant):
        async with db_state.session_factory() as s:
            found = await subscribers_by_uuid(s, tenant_id=tenant, type_key=key, uuids=[uuid])
    return found[uuid].status
