"""A three-subscriber list for the newsletter contract's tests (newsletter PR 1).

``audience``: on the submissions harness, the list ``news`` with a ``tags``
multiselect (``a``, ``b``) and ada (confirmed, ``a``), bob (confirmed, ``b``)
and cy (pending, ``a``+``b``), all signed up through the real public routes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import pytest_asyncio
from simple_module_db.listeners import current_tenant_id
from sm_records.contracts.events import SubscriptionChanged
from sm_records.core import boot, events
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.records.services import records as record_service
from sm_records.records.services import types as type_service
from sm_records.records.services._common import utcnow

from tests.support.app_harness import field
from tests.support.newsletter_http import LIST, follow, links_in, list_config, list_fields, signup
from tests.support.public_submissions_support import create

TENANT = "default"
TAGS = field(
    "tags",
    "multiselect",
    choices=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
)


async def join(client, address: str, tags: list[str], *, confirm: bool) -> dict[str, str]:
    """Sign ``address`` up (and confirm it); the confirmation mail's tokens."""
    sent = len(client.outbox.sent)
    assert (await signup(client, address, data={"tags": tags})).status_code == 202
    tokens = {action: v["t"] for action, v in links_in(client.outbox.sent[sent]).items()}
    if confirm:
        assert (await follow(client, "confirm", tokens["confirm"])).status_code == 200
    return tokens


@pytest_asyncio.fixture
async def audience(site):
    boot.mount_submission_views(site.app)
    config = list_config(public_fields=["first_name", "tags"])
    resp = await create(site, LIST, fields=[*list_fields(), TAGS], config=config)
    assert resp.status_code == 201, resp.text
    await join(site, "ada@example.org", ["a"], confirm=True)
    await join(site, "bob@example.org", ["b"], confirm=True)
    await join(site, "cy@example.org", ["a", "b"], confirm=False)
    return site


@asynccontextmanager
async def session(client) -> AsyncIterator[Any]:
    async with client.db_state.session_factory() as db:
        yield db


@contextmanager
def unbound() -> Iterator[None]:
    """No tenant bound for the block — a host with ``multi_tenant`` off, or a
    worker, before the contract binds the one it is told."""
    token = current_tenant_id.set(None)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


async def seed_list(db_state: Any, tenant: str, email: str) -> str:
    """In ``tenant``, the list ``news`` with one confirmed subscriber; its uuid.

    Written through the services in a session of its own, bound to ``tenant``
    (one session never serves two tenants)."""
    settings = RecordsSettings()
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            rtype = await type_service.create_type(
                db,
                key=LIST,
                label=tenant,
                fields_raw=[*list_fields(), TAGS],
                public_submissions=list_config(),
                settings=settings,
            )
            record = await record_service.create_record(
                db,
                rtype,
                data={},
                settings=settings,
                system={
                    "sm_email": email,
                    "sm_status": "confirmed",
                    "sm_confirmed_at": utcnow(),
                    "sm_locale": "en",
                    "sm_nonce": "0" * 32,
                },
            )
            await events.commit(db)
            return record.uuid


def subscription_events(client) -> list:
    """Every ``SubscriptionChanged`` the app's bus publishes from now on."""
    seen: list = []

    async def note(event):
        seen.append(event)

    client.app.state.sm.event_bus.subscribe(SubscriptionChanged, note)
    return seen


def transitions(seen: list) -> Iterator[tuple[str | None, str]]:
    return ((e.status_before, e.status_after) for e in seen)
