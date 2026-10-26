"""Seeding and sweeping for the retention tests (#101): records whose
timestamps lie in the past, delivery rows, and a sweep at a fixed ``NOW``."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import timedelta

from sm_records.models import SubmissionDelivery, tables_for
from sm_records.public_submissions import retention
from sm_records.services import records as record_service
from sm_records.services import types as type_service
from sm_records.services._common import utcnow
from sm_records.settings import RecordsSettings
from sqlalchemy import select, update

from tests.app_harness import build_app
from tests.public_submissions_support import contact_fields, form_config
from tests.tenancy_support import session_in

S = RecordsSettings(reindex_batch_size=2)
NOW = utcnow()
DATA = {"name": "Ada", "email": "ada@example.org", "message": "Hello"}


class Bus:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


@asynccontextmanager
async def temp_db(tmp_path):
    """A database with every records table; each test file wraps it in its
    own ``db`` fixture."""
    _, db_state = await build_app(tmp_path)
    try:
        yield db_state
    finally:
        await db_state.engine.dispose()


async def form(db, tenant: str = "default", key: str = "contact", **config):
    async with session_in(db, tenant) as session:
        return await type_service.create_type(
            session,
            key=key,
            label=key.title(),
            settings=S,
            fields_raw=contact_fields(),
            public_submissions=form_config(enabled=True, **config),
        )


async def newsletter(db, tenant: str = "default", key: str = "news"):
    async with session_in(db, tenant) as session:
        return await type_service.create_type(
            session,
            key=key,
            label=key.title(),
            settings=S,
            fields_raw=[],
            public_submissions={"kind": "subscription", "enabled": True},
        )


async def record(
    db,
    key: str,
    *,
    age_days: float,
    tenant="default",
    trashed=False,
    updated_days: float | None = None,
    **system,
):
    """A record of ``key`` whose ``created_at`` (and ``updated_at``, unless
    ``updated_days`` says otherwise) is ``age_days`` in the past; its uuid."""
    async with session_in(db, tenant) as session:
        rtype = await type_service.get_type(session, key)
        data = {} if rtype.public_submissions["kind"] == "subscription" else dict(DATA)
        record = await record_service.create_record(
            session, rtype, data=data, settings=S, system=system or None
        )
        if trashed:
            await record_service.soft_delete_record(session, rtype, record, settings=S)
        cls = tables_for(rtype).record
        then = NOW - timedelta(days=age_days)
        await session.execute(
            update(cls)
            .where(cls.id == record.id, cls.tenant_id == tenant)
            .values(
                created_at=then,
                updated_at=then if updated_days is None else NOW - timedelta(days=updated_days),
            )
            .execution_options(include_deleted=True)
        )
        return record.uuid


def subscriber(status: str) -> dict:
    return {
        "sm_email": f"{secrets.token_hex(4)}@example.org",
        "sm_status": status,
        "sm_nonce": secrets.token_hex(16),
    }


async def uuids(db, key: str, tenant: str = "default") -> set[str]:
    async with session_in(db, tenant) as session:
        rtype = await type_service.get_type(session, key)
        cls = tables_for(rtype).record
        stmt = select(cls.uuid).where(cls.type_id == rtype.id, cls.tenant_id == tenant)
        rows = await session.execute(stmt.execution_options(include_deleted=True))
        return set(rows.scalars().all())


async def claim(
    db, uuid: str, *, tenant="default", sent=None, claimed=None, who="ops@x.org", attempt=None
):
    async with session_in(db, tenant) as session:
        session.add(
            SubmissionDelivery(
                tenant_id=tenant,
                record_uuid=uuid,
                attempt=attempt or secrets.token_hex(8),
                recipient=who,
                claimed_at=claimed,
                sent_at=sent,
            )
        )


async def claims(db, tenant: str = "default") -> list[tuple[str, str]]:
    async with session_in(db, tenant) as session:
        table = SubmissionDelivery
        rows = await session.execute(
            select(table.record_uuid, table.recipient).where(table.tenant_id == tenant)
        )
        return sorted((str(a), str(b)) for a, b in rows.all())


async def sweep(db, bus=None, settings: RecordsSettings = S):
    return await retention.sweep(db.session_factory, settings, bus=bus, now=NOW)
