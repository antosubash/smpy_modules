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
from sqlalchemy import select, update

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
        slot = delivery.Slot("default", event.uuid, event.attempt, "alice@example.org")
        assert (await delivery.claim(factory, slot))[0] == "claimed"
        assert await delivery.claim(factory, slot) == ("busy", None), "hands off a live claim"
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
        slot = delivery.Slot("default", event.uuid, event.attempt, "alice@example.org")
        results = await asyncio.gather(*(delivery.claim(factory, slot) for _ in range(5)))
    assert sorted(state for state, _ in results) == ["busy"] * 4 + ["claimed"]


async def _age(factory) -> None:
    stale = utcnow() - delivery.LEASE - timedelta(seconds=1)
    session = factory()
    await session.execute(update(SubmissionDelivery).values(claimed_at=stale))
    await events.commit(session)
    await session.close()


async def test_a_stale_owner_can_neither_release_nor_complete_its_successors_claim(site):
    factory = site.db_state.session_factory
    slot = delivery.Slot("default", "c" * 32, "attempt-1", "alice@example.org")
    with tenant_scope("default"):
        state, stale = await delivery.claim(factory, slot)
        assert state == "claimed" and stale
        assert await delivery.claim(factory, slot) == ("busy", None), "no takeover before expiry"
        await _age(factory)
        state, fresh = await delivery.claim(factory, slot)
        assert state == "claimed" and fresh != stale, "taken over once the lease expired"
        assert await delivery.release(factory, slot, stale) is False
        assert await delivery.claim(factory, slot) == ("busy", None), "the successor still holds it"
        assert await delivery.mark_sent(factory, slot, stale) is False
        session = factory()
        row = (await session.execute(select(SubmissionDelivery))).scalar_one()
        assert row.sent_at is None and row.claim_token == fresh
        await session.close()
        assert await delivery.mark_sent(factory, slot, fresh) is True
        assert await delivery.claim(factory, slot) == ("sent", None)


async def test_a_send_that_hangs_is_cut_off_and_released(site, monkeypatch):
    monkeypatch.setattr(delivery, "SEND_TIMEOUT", timedelta(seconds=0.05))
    transport = _durable(site)
    await contact_type(site, notify_to=["alice@example.org"])
    await send(site)
    (event,) = transport.events

    async def hang(message) -> None:
        await asyncio.sleep(5)

    real = site.outbox.send
    site.outbox.send = hang  # type: ignore[method-assign]
    with pytest.raises(TimeoutError):
        await _run(site, event)
    site.outbox.send = real  # type: ignore[method-assign]
    await _run(site, event)
    assert _to(site) == ["alice@example.org"], "the released claim is retried at once"


async def _complete_rows(site) -> list[str]:
    with tenant_scope("default"):
        session = site.db_state.session_factory()
        try:
            stmt = select(SubmissionDelivery.attempt).where(
                SubmissionDelivery.recipient == delivery.COMPLETE
            )
            return list((await session.execute(stmt)).scalars().all())
        finally:
            await session.close()


async def test_an_attempt_is_recorded_complete_only_once_everyone_is_sent(site):
    """Pruning trusts this row alone (``retention_deliveries``)."""
    transport = _durable(site)
    await contact_type(site, notify_to=TWO)
    await send(site)
    (event,) = transport.events
    site.outbox.fail_for = {"bob@example.org"}
    with pytest.raises(OSError):
        await _run(site, event)
    assert await _complete_rows(site) == [], "bob is still owed: not complete"
    site.outbox.fail_for = set()
    await _run(site, event)
    assert await _complete_rows(site) == [delivery.attempt_of(event)]
    await _run(site, event)
    assert len(await _complete_rows(site)) == 1, "a redelivery writes it once"
