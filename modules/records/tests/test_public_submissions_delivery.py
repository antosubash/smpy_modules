"""Per-recipient delivery claims (#101): a recipient whose send was recorded is
never mailed again by any retry of its attempt, attempts do not overwrite each
other, two workers cannot both send, and a crashed claim is retried."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from simple_module_core.durable_events import DurableContext
from sm_records import events
from sm_records.models import SubmissionDelivery
from sm_records.public_submissions import delivery
from sm_records.public_submissions.mail_runner import HANDLER_NAME, NotificationDue
from sm_records.services._common import utcnow
from sm_records.tenancy import tenant_scope
from sqlalchemy import update

from tests.app_harness import ADMIN, roles
from tests.pg_support import USING_POSTGRES
from tests.submissions_http import contact_type, records_of, send

pytestmark = pytest.mark.unbound_tenant
TWO = ["alice@example.org", "bob@example.org"]


class Transport:
    def __init__(self) -> None:
        self.events: list[NotificationDue] = []

    async def enqueue(self, event, handler_names, db) -> None:
        self.events.append(event)


def _durable(site) -> Transport:
    bus = site.app.state.sm.event_bus
    site.app.state.records_module.register_event_handlers(bus, site.app)
    bus.durable_transport = transport = Transport()
    return transport


async def _run(site, event) -> None:
    bus = site.app.state.sm.event_bus
    key = "sm_records.public_submissions.mail_runner.NotificationDue"
    handler = bus.durable.lookup(key, HANDLER_NAME).handler
    session = site.db_state.session_factory()
    try:
        await handler(event, DurableContext(db=session, attempt=1))
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()


def _to(site) -> list[str]:
    return [message.to for message in site.outbox.sent]


async def test_a_resend_does_not_erase_the_first_attempts_progress(site):
    transport = _durable(site)
    await contact_type(site, notify_to=TWO)
    await send(site)
    (first,) = transport.events
    site.outbox.fail_for = {"bob@example.org"}
    with pytest.raises(OSError):
        await _run(site, first)
    site.outbox.fail_for = set()
    (record,) = await records_of(site)
    url = f"/api/records/types/contact/records/{record['uuid']}/submission/resend"
    assert (await site.post(url, headers=roles(ADMIN))).status_code == 202
    _, resend = transport.events
    await _run(site, resend)
    await _run(site, first)
    assert sorted(_to(site)) == sorted([*TWO, "alice@example.org", "bob@example.org"]), (
        "alice: once per attempt, never twice in the first"
    )


async def test_a_legacy_event_without_an_attempt_has_a_stable_identity(site):
    transport = _durable(site)
    await contact_type(site, notify_to=TWO)
    await send(site)
    (event,) = transport.events
    legacy = NotificationDue(**{**event.__dict__, "attempt": ""})
    site.outbox.fail_for = {"bob@example.org"}
    with pytest.raises(OSError):
        await _run(site, legacy)
    site.outbox.fail_for = set()
    await _run(site, NotificationDue(**{**event.__dict__, "attempt": ""}))
    assert _to(site) == TWO
    assert delivery.attempt_of(legacy).startswith("legacy-")


async def test_a_live_claim_blocks_and_an_expired_one_is_taken_over(site):
    transport = _durable(site)
    await contact_type(site, notify_to=["alice@example.org"])
    await send(site)
    (event,) = transport.events
    factory = site.db_state.session_factory
    with tenant_scope("default"):
        args = (factory, "default", event.uuid, event.attempt, "alice@example.org")
        assert await delivery.claim(*args) == "claimed"
        assert await delivery.claim(*args) == "busy", "a second worker keeps its hands off"
        with pytest.raises(delivery.DeliveryInProgress):
            await _run(site, event)
        assert _to(site) == [] and (await records_of(site))[0]["data"]["sm_notified_at"] is None
        stale = utcnow() - delivery.LEASE - timedelta(seconds=1)
        session = factory()
        await session.execute(update(SubmissionDelivery).values(claimed_at=stale))
        await events.commit(session)
        await session.close()
    await _run(site, event)
    assert _to(site) == ["alice@example.org"], "the crashed worker's claim expired"
    await _run(site, event)
    assert _to(site) == ["alice@example.org"], "recorded as sent: never again"


@pytest.mark.skipif(not USING_POSTGRES, reason="a real concurrent INSERT race needs Postgres")
async def test_two_workers_racing_for_one_recipient_send_once(site):
    transport = _durable(site)
    await contact_type(site, notify_to=["alice@example.org"])
    await send(site)
    (event,) = transport.events
    factory = site.db_state.session_factory
    with tenant_scope("default"):
        args = (factory, "default", event.uuid, event.attempt, "alice@example.org")
        results = await asyncio.gather(*(delivery.claim(*args) for _ in range(5)))
    assert sorted(results) == ["busy"] * 4 + ["claimed"]
