"""Records lists and subscribers for newsletter tests, written through records'
own services (test-only imports: module code reads records only through
``sm_records.contracts``).

Each helper opens a session of its own, bound to the tenant it is given, and
finishes it with records' ``events.commit`` so the write is what the contract
reads back.
"""

from __future__ import annotations

import secrets
import time
from types import SimpleNamespace
from typing import Any

from sm_records.contracts.public_submissions_api import SubmitBody
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.public_submissions import links, opt_in, subscribe
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service
from sm_records.records.services._common import utcnow
from starlette.requests import Request

LIST = "news"
# What records' newsletter contract writes take: the app they read records'
# settings off (#336), here holding the defaults.
RECORDS_APP = SimpleNamespace(
    state=SimpleNamespace(sm_records=SimpleNamespace(settings=RecordsSettings()))
)
TAGS = {
    "key": "tags",
    "type": "multiselect",
    "label": "Tags",
    "indexed": True,
    "options": {
        "choices": [{"value": "vip", "label": "VIP"}, {"value": "events", "label": "Events"}]
    },
}


async def seed_list(
    db_state: Any,
    tenant: str,
    key: str = LIST,
    *,
    double_opt_in: bool | None = None,
    allowed_roles: list[str] | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> None:
    """In ``tenant``, the newsletter list ``key`` (a subscription-kind type);
    records' default is double opt-in. Without it records requires consent.
    ``allowed_roles`` narrows who may read it (records' design §10)."""
    config: dict[str, Any] = {"kind": "subscription", "enabled": True}
    if double_opt_in is not None:
        config["double_opt_in"] = double_opt_in
    if double_opt_in is False:
        config["consent"] = {"required": True, "text": {"en": "Send me the newsletter."}}
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            await type_service.create_type(
                db,
                key=key,
                label=key,
                fields_raw=list(fields or []),
                public_submissions=config,
                settings=RecordsSettings(),
                allowed_roles=allowed_roles,
            )
            await events.commit(db)


async def restrict_list(db_state: Any, tenant: str, key: str, allowed_roles: list[str]) -> None:
    """Narrow list ``key`` in ``tenant`` to ``allowed_roles`` after the fact, as
    an admin editing the type would."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            rtype = await type_service.get_type(db, key)
            rtype.allowed_roles = list(allowed_roles)
            await events.commit(db)


async def set_list_kind(db_state: Any, tenant: str, key: str, kind: str) -> None:
    """Turn type ``key`` into another kind (``"form"``: no longer a list) or
    back (``"subscription"``), as an admin editing the type would."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            rtype = await type_service.get_type(db, key)
            rtype.public_submissions = {**(rtype.public_submissions or {}), "kind": kind}
            await events.commit(db)


async def seed_subscriber(
    db_state: Any,
    tenant: str,
    email: str,
    status: str,
    key: str = LIST,
    *,
    trashed: bool = False,
    data: dict[str, Any] | None = None,
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
                db, rtype, data=dict(data or {}), settings=settings, system=system
            )
            if trashed:
                await record_service.soft_delete_record(db, rtype, record, settings=settings)
            await events.commit(db)
            return record.uuid


async def backdate(db_state: Any, tenant: str, uuid: str, created_at: Any, key: str = LIST) -> None:
    """Set a subscriber's ``created_at`` (test-only: through records' tables)."""
    from sm_records.models import tables_for
    from sqlalchemy import update

    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            rtype = await type_service.get_type(db, key)
            table = tables_for(rtype).record
            await db.execute(
                update(table)
                .where(table.uuid == uuid, table.tenant_id == tenant)
                .values(created_at=created_at)
            )
            await events.commit(db)


# Records' public-submissions paths without the HTTP layer: no form token,
# no rate limit, no confirmation mail.
_SECRET = "newsletter-tests-link-secret"
_NO_IP = RecordsSettings(public_submissions_store_ip_hash=False)


async def signup(db_state: Any, tenant: str, email: str, bus: Any, key: str = LIST) -> str:
    """A website signup of ``email`` through records' own state machine
    (``subscribe._fresh`` decides the status from the list's double opt-in,
    ``subscribe._write`` writes it), announced to ``bus``; its uuid."""
    request = Request({"type": "http", "headers": [], "app": None, "client": None})
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            events.attach(db, bus)
            rtype = await type_service.get_type(db, key)
            fresh = subscribe._fresh(request, rtype, SubmitBody(), _NO_IP, email)
            existing = await subscribe.find(db, rtype, email)
            record, before, wrote = await subscribe._write(db, rtype, existing, {}, fresh, _NO_IP)
            if wrote:
                after = (record.data or {}).get("sm_status")
                events.emit(db, subscribe.changed(rtype, record, before, after))
            await events.commit(db)
            return record.uuid


async def confirm_link(db_state: Any, tenant: str, uuid: str, bus: Any, key: str = LIST) -> str:
    """The subscriber follows the confirm link records mails it
    (``opt_in.confirm``), announced to ``bus``; records' answer."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            events.attach(db, bus)
            rtype = await type_service.get_type(db, key)
            record = await record_service.get_record(db, rtype, uuid)
            token = links.sign(
                _SECRET,
                links.CONFIRM,
                tenant=tenant,
                type_key=key,
                uuid=uuid,
                nonce=record.data["sm_nonce"],
                exp=int(time.time()) + 3600,
            )
            link = links.parse(_SECRET, links.CONFIRM, token)
            answer = await opt_in.confirm(db, _SECRET, link, _NO_IP)
            await events.commit(db)
            return answer
