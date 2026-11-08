"""Helpers for the newsletter import contract's tests (newsletter PR 7, task 2).

``make_list``: a list made by ``create_list`` (``first_name``, ``last_name``),
with a ``team`` select (``x``/``X``) added and ``tags`` choices ``a`` and ``b``.
``seed`` writes a subscriber in any state through records' services;
``run`` imports in a session of its own with a spy bus attached and commits.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sm_records.contracts.newsletter_import import (
    ImportResult,
    ImportRow,
    create_list,
    import_subscribers,
)
from sm_records.core import events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.models import Record
from sm_records.public_submissions import subscribe
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service

from tests.support.app_harness import field
from tests.support.newsletter_contract import TENANT, session, unbound

SETTINGS = RecordsSettings()
KEY = "weekly"
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
T = NOW - timedelta(days=30)
ADA = "ada@example.org"


class Spy:
    """A bus that records everything published to it."""

    def __init__(self) -> None:
        self.seen: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.seen.append(event)


async def make_list(site, tenant: str = TENANT, key: str = KEY) -> None:
    async with session(site) as db:
        with unbound():
            await create_list(db, tenant_id=tenant, key=key, label="Weekly", settings=SETTINGS)
            await events.commit(db)
    with unbound(), tenant_scope(tenant):
        async with session(site) as db:
            rtype = await type_service.get_type(db, key)
            team = field("team", "select", choices=[{"value": "x", "label": "X"}])
            tags = field(
                "tags",
                "multiselect",
                choices=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
            )
            await type_service.update_type(
                db,
                rtype,
                fields_raw=[*rtype.fields, team, tags],
                expected_version=rtype.version,
                settings=SETTINGS,
            )
            await events.commit(db)


def system(email: str, status: str, confirmed_at: datetime | None = None) -> dict[str, Any]:
    return {
        "sm_email": email,
        "sm_status": status,
        "sm_confirmed_at": confirmed_at if status == "confirmed" else None,
        "sm_unsubscribed_at": T if status == "unsubscribed" else None,
        "sm_consent_text": None if status == "unsubscribed" else "Yes please",
        "sm_locale": "en",
        "sm_nonce": secrets.token_hex(16),
    }


async def seed(
    site,
    email: str,
    status: str = "confirmed",
    *,
    data: dict[str, Any] | None = None,
    confirmed_at: datetime | None = T,
    trashed: bool = False,
    tenant: str = TENANT,
    key: str = KEY,
) -> None:
    with unbound(), tenant_scope(tenant):
        async with session(site) as db:
            rtype = await type_service.get_type(db, key)
            record = await record_service.create_record(
                db,
                rtype,
                data=data or {},
                settings=SETTINGS,
                system=system(email, status, confirmed_at),
            )
            if trashed:
                await record_service.soft_delete_record(db, rtype, record, settings=SETTINGS)
            await events.commit(db)


async def stored(site, email: str, tenant: str = TENANT, key: str = KEY) -> Record:
    """The record holding ``email`` (trash included), read through the ORM."""
    with unbound(), tenant_scope(tenant):
        async with session(site) as db:
            rtype = await type_service.get_type(db, key)
            found = await subscribe.find(db, rtype, email)
            assert found is not None, email
            return found


async def run(
    site,
    rows: Sequence[ImportRow],
    *,
    tenant: str = TENANT,
    key: str = KEY,
    spy: Spy | None = None,
    now: datetime = NOW,
) -> list[ImportResult]:
    async with session(site) as db:
        events.attach(db, spy or Spy())
        with unbound():
            results = await import_subscribers(
                db, tenant_id=tenant, type_key=key, rows=rows, settings=SETTINGS, now=now
            )
        await events.commit(db)
    return results


def row(email: str, status: str = "confirmed", **kw) -> ImportRow:
    return ImportRow(email=email, status=status, **kw)


def outcomes(results: Sequence[ImportResult]) -> dict[str, str]:
    return {r.email: r.outcome for r in results}
