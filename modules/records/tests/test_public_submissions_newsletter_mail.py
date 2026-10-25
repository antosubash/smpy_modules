"""The newsletter's confirmation mail (#101, design §6): never through the
outbox, never re-sent within one attempt, lost sends visible and recoverable,
and an unsubscribe that a schema misfit cannot block."""

from __future__ import annotations

import pytest
from sm_records.models import RecordType, tables_for
from sm_records.public_submissions import mail_runner
from sqlalchemy import select, update

from tests.app_harness import ADMIN, field, roles
from tests.newsletter_http import (
    LIST,
    admin,
    follow,
    links_in,
    list_config,
    signup,
    subscriber,
)
from tests.public_submissions_support import create

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


async def _misfit(site, record: dict, key: str = LIST, **values) -> None:
    """Rewrite the stored payload behind the schema's back (a forced change)."""
    from sm_records.tenancy import tenant_scope

    async with site.db_state.session_factory() as session:
        with tenant_scope("default"):
            stmt = select(RecordType).where(RecordType.key == key)
            rtype = (await session.execute(stmt)).scalar_one()
            cls = tables_for(rtype).record
            await session.execute(
                update(cls)
                .where(cls.uuid == record["uuid"], cls.tenant_id == "default")
                .values(data={**record["data"], **values})
            )
            await session.commit()


async def test_an_unsubscribe_reaches_a_record_that_fails_its_schema(newsletter):
    """A forced restrictive change left an *optional* value invalid: the
    unsubscribe clears it, so the ordinary write lands — index row included,
    so the filter finds the record."""
    await signup(newsletter, data={"first_name": "Ada"})
    tokens = links_in(newsletter.outbox.sent[0])
    record = await subscriber(newsletter)
    await _misfit(newsletter, record, first_name="x" * 500)  # over max_length 100
    resp = await follow(newsletter, "unsubscribe", tokens["unsubscribe"]["t"])
    assert resp.json() == {"status": "unsubscribed"}
    data = (await subscriber(newsletter))["data"]
    assert data["sm_status"] == "unsubscribed" and data["sm_consent_at"] is None
    assert data.get("first_name") is None, "optional values cleared in the same step"
    found = await newsletter.get(
        f"/api/records/types/{LIST}/records?filter=sm_status:eq:unsubscribed",
        headers=roles(ADMIN),
    )
    assert [r["uuid"] for r in found.json()["items"]] == [record["uuid"]]


async def test_the_fallback_clears_optional_values_and_a_unique_one_never_blocks(site):
    """A *required* value the schema now refuses keeps the ordinary write
    from landing, so the guarded merge writes the unsubscribe: the status and
    nonce, the optional ``city`` cleared in the same step — and the unique
    ``member_id``, whose claim only the ordinary write may check, left as it
    is (and logged) rather than blocking anything."""
    first = field("first_name", required=True, indexed=False)
    first["constraints"] = {"max_length": 100}
    member = field("member_id", unique=True)
    city = field("city", indexed=False)
    config = list_config(public_fields=["first_name"])
    resp = await create(site, "club", fields=[first, member, city], config=config)
    assert resp.status_code == 201, resp.text
    await signup(site, key="club", data={"first_name": "Ada"})
    tokens = links_in(site.outbox.sent[0])
    record = await subscriber(site, "club")
    await _misfit(site, record, "club", first_name="x" * 500, member_id="M-1", city="Berlin")
    await follow(site, "unsubscribe", tokens["unsubscribe"]["t"])
    data = (await subscriber(site, "club"))["data"]
    assert data["sm_status"] == "unsubscribed" and data["sm_nonce"] != record["data"]["sm_nonce"]
    assert data["city"] is None, "cleared by the direct merge"
    assert data["member_id"] == "M-1" and data["first_name"] == "x" * 500


async def test_an_unchanged_unique_value_does_not_block_the_direct_merge(site):
    """A change that names the subscriber's own ``sm_email`` again (a
    re-subscribe's system values) still lands on a misfit record."""
    from sm_records.public_submissions.transition import transition
    from sm_records.services.records import get_record
    from sm_records.settings import RecordsSettings
    from sm_records.tenancy import tenant_scope

    first = field("first_name", required=True, indexed=False)
    first["constraints"] = {"max_length": 100}
    config = list_config(public_fields=["first_name"])
    assert (await create(site, "club", fields=[first], config=config)).status_code == 201
    await signup(site, key="club", data={"first_name": "Ada"})
    record = await subscriber(site, "club")
    await _misfit(site, record, "club", first_name="x" * 500)
    values = {"sm_email": record["data"]["sm_email"], "sm_status": "unsubscribed"}
    async with site.db_state.session_factory() as session:
        with tenant_scope("default"):
            stmt = select(RecordType).where(RecordType.key == "club")
            rtype = (await session.execute(stmt)).scalar_one()
            row = await get_record(session, rtype, record["uuid"])
            outcome = await transition(
                session, rtype, row, lambda _row: (values, None), settings=RecordsSettings()
            )
            await session.commit()
    assert outcome.wrote
    assert (await subscriber(site, "club"))["data"]["sm_status"] == "unsubscribed"
