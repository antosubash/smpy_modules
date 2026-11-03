"""Records lists and subscribers for newsletter tests, written through records'
own services (test-only imports: module code reads records only through
``sm_records.contracts``).

Each helper opens a session of its own, bound to the tenant it is given, and
finishes it with records' ``events.commit`` so the write is what the contract
reads back.
"""

from __future__ import annotations

import secrets
from typing import Any

from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service
from sm_records.records.services._common import utcnow

LIST = "news"


async def seed_list(db_state: Any, tenant: str, key: str = LIST) -> None:
    """In ``tenant``, the newsletter list ``key`` (a subscription-kind type)."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            await type_service.create_type(
                db,
                key=key,
                label=key,
                fields_raw=[],
                public_submissions={"kind": "subscription", "enabled": True},
                settings=RecordsSettings(),
            )
            await events.commit(db)


async def seed_subscriber(
    db_state: Any,
    tenant: str,
    email: str,
    status: str,
    key: str = LIST,
    *,
    trashed: bool = False,
) -> str:
    """One subscriber of ``key`` in ``tenant`` with ``status``; its uuid.

    A ``confirmed`` one carries ``sm_confirmed_at`` (now)."""
    settings = RecordsSettings()
    system: dict[str, Any] = {
        "sm_email": email,
        "sm_status": status,
        "sm_locale": "en",
        "sm_nonce": secrets.token_hex(16),
    }
    if status == "confirmed":
        system["sm_confirmed_at"] = utcnow()
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            rtype = await type_service.get_type(db, key)
            record = await record_service.create_record(
                db, rtype, data={}, settings=settings, system=system
            )
            if trashed:
                await record_service.soft_delete_record(db, rtype, record, settings=settings)
            await events.commit(db)
            return record.uuid
