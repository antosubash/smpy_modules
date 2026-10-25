"""The notification's two delivery paths (#101): the outbox when the host has
a durable transport, and the after-commit task otherwise."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from simple_module_core.durable_events import DurableContext, serialize_event
from simple_module_core.mail import install_mail_sender
from sm_records.public_submissions import mail_runner
from sm_records.public_submissions.mail_runner import HANDLER_NAME, MailUnavailable

from tests.submissions_http import (
    contact_type,
    records_of,
    send,
)

pytestmark = pytest.mark.unbound_tenant


class FakeTransport:
    """Keeps what would have been written to the outbox."""

    def __init__(self) -> None:
        self.rows: list[tuple] = []

    async def enqueue(self, event, handler_names, db) -> None:
        self.rows.append((event, list(handler_names), serialize_event(event)))


def _durable(site) -> FakeTransport:
    bus = site.app.state.sm.event_bus
    site.app.state.records_module.register_event_handlers(bus, site.app)
    bus.durable_transport = transport = FakeTransport()
    return transport


def _handler(site):
    bus = site.app.state.sm.event_bus
    key = "sm_records.public_submissions.mail_runner.NotificationDue"
    return bus.durable.lookup(key, HANDLER_NAME).handler


async def test_the_handler_is_registered_without_an_app(site):
    """The outbox worker builds modules with ``app=None``."""
    from simple_module_core.events import EventBus

    bus = EventBus()
    site.app.state.records_module.register_event_handlers(bus, None)
    assert bus.durable.handler_names(mail_runner.NotificationDue) == [HANDLER_NAME]


async def test_with_an_outbox_the_request_only_enqueues_identifiers(site):
    transport = _durable(site)
    await contact_type(site)
    assert (await send(site)).status_code == 202
    assert site.outbox.sent == [], "nothing is sent inside the request"
    ((_event, names, payload),) = transport.rows
    assert names == [HANDLER_NAME]
    assert set(payload) == {"tenant_id", "type_key", "uuid", "base_url", "locale"}
    assert "Ada" not in str(payload) and "ada@example.org" not in str(payload)
    assert payload["tenant_id"] == "default" and payload["base_url"] == "https://site.example"


async def test_the_handler_binds_the_tenant_sends_and_marks_without_committing(site):
    transport = _durable(site)
    await contact_type(site)
    await send(site)
    ((event, _, _),) = transport.rows
    session = site.db_state.session_factory()
    commit = session.commit
    calls: list[str] = []

    async def counted() -> None:
        calls.append("commit")

    session.commit = counted  # type: ignore[method-assign]
    try:
        await _handler(site)(event, DurableContext(db=session, attempt=1))
        assert [m.to for m in site.outbox.sent] == ["ops@example.org"]
        assert calls == [] and session.in_transaction(), "the handler never commits ctx.db"
        await commit()
    finally:
        await session.close()
    (record,) = await records_of(site)
    assert record["data"]["sm_notified_at"], "the transport's commit lands the mark"


async def test_the_handler_raises_while_no_transport_is_installed(site):
    transport = _durable(site)
    await contact_type(site)
    await send(site)
    ((event, _, _),) = transport.rows
    install_mail_sender(None)
    with pytest.raises(MailUnavailable):
        await _handler(site)(event, SimpleNamespace(db=None, attempt=1))


async def test_the_handler_skips_a_record_that_has_gone(site):
    transport = _durable(site)
    await contact_type(site)
    await send(site)
    ((event, _, _),) = transport.rows
    (record,) = await records_of(site)
    from tests.app_harness import ADMIN, roles

    gone = await site.delete(
        f"/api/records/types/contact/records/{record['uuid']}", headers=roles(ADMIN)
    )
    assert gone.status_code == 204
    session = site.db_state.session_factory()
    try:
        await _handler(site)(event, DurableContext(db=session, attempt=1))
    finally:
        await session.close()
    assert site.outbox.sent == []


async def test_after_commit_a_send_failure_leaves_the_record_not_sent(site):
    await contact_type(site)
    site.outbox.fail = True
    assert (await send(site)).status_code == 202, "a mail failure never fails the submission"
    (record,) = await records_of(site)
    assert record["data"]["sm_notified_at"] is None
