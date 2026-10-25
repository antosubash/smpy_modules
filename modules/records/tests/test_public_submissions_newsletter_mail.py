"""The newsletter's confirmation mail (#101, design §6): never through the
outbox, never re-sent within one attempt, lost sends visible and recoverable,
and an unsubscribe that a schema misfit cannot block."""

from __future__ import annotations

import pytest
from sm_records.models import RecordType, tables_for
from sm_records.public_submissions import mail_runner
from sqlalchemy import select, update

from tests.app_harness import ADMIN, roles
from tests.newsletter_http import (
    LIST,
    admin,
    follow,
    links_in,
    signup,
    subscriber,
)

pytestmark = pytest.mark.unbound_tenant


class FakeTransport:
    def __init__(self) -> None:
        self.rows: list = []

    async def enqueue(self, event, handler_names, db) -> None:
        self.rows.append(event)


async def test_the_confirmation_never_goes_through_the_outbox(newsletter):
    """Its links need the host's ``secret_key``, which the worker lacks."""
    bus = newsletter.app.state.sm.event_bus
    newsletter.app.state.records_module.register_event_handlers(bus, newsletter.app)
    bus.durable_transport = transport = FakeTransport()
    assert (await signup(newsletter)).status_code == 202
    assert transport.rows == []
    (message,) = newsletter.outbox.sent
    assert set(links_in(message)) == {"confirm", "unsubscribe"}


async def test_a_failed_confirmation_stays_not_sent_and_resend_recovers_it(newsletter):
    newsletter.outbox.fail = True
    assert (await signup(newsletter)).status_code == 202, "a mail failure is not the visitor's"
    record = await subscriber(newsletter)
    assert record["data"]["sm_confirm_sent_at"] is None
    newsletter.outbox.fail = False
    assert (await admin(newsletter, record["uuid"], "resend")).status_code == 202
    await mail_runner.drain()
    (message,) = newsletter.outbox.sent
    assert (await subscriber(newsletter))["data"]["sm_confirm_sent_at"]
    confirm = links_in(message)["confirm"]["t"]
    assert (await follow(newsletter, "confirm", confirm)).json() == {"status": "confirmed"}


async def test_a_subscriber_no_longer_pending_is_not_mailed(newsletter, monkeypatch):
    """Built when the task runs, from the record as it is then."""
    from sm_records.public_submissions import confirmation

    held: list = []

    async def hold(db, app, due, work, *, durable=True):
        held.append((app, due, work))

    monkeypatch.setattr(confirmation, "queue", hold)
    await signup(newsletter)
    record = await subscriber(newsletter)
    await admin(newsletter, record["uuid"], "unsubscribe")
    ((app, due, work),) = held
    await mail_runner._run(app, due, work)
    assert newsletter.outbox.sent == []


async def test_an_unsubscribe_reaches_a_record_that_fails_its_schema(newsletter):
    """A forced restrictive change left the row invalid: the ordinary write is
    refused, and the guarded compare-and-set writes the status — index row
    included, so the filter finds it."""
    await signup(newsletter, data={"first_name": "Ada"})
    tokens = links_in(newsletter.outbox.sent[0])
    record = await subscriber(newsletter)
    async with newsletter.db_state.session_factory() as session:
        from sm_records.tenancy import tenant_scope

        with tenant_scope("default"):
            rtype = (
                await session.execute(select(RecordType).where(RecordType.key == LIST))
            ).scalar_one()
            cls = tables_for(rtype).record
            misfit = {**record["data"], "first_name": "x" * 500}  # over max_length 100
            await session.execute(
                update(cls)
                .where(cls.uuid == record["uuid"], cls.tenant_id == "default")
                .values(data=misfit)
            )
            await session.commit()
    resp = await follow(newsletter, "unsubscribe", tokens["unsubscribe"]["t"])
    assert resp.json() == {"status": "unsubscribed"}
    data = (await subscriber(newsletter))["data"]
    assert data["sm_status"] == "unsubscribed" and data["sm_consent_at"] is None
    found = await newsletter.get(
        f"/api/records/types/{LIST}/records?filter=sm_status:eq:unsubscribed",
        headers=roles(ADMIN),
    )
    assert [r["uuid"] for r in found.json()["items"]] == [record["uuid"]]
