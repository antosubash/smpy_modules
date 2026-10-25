"""A purge and a confirmation's claim never leave a claim — or a mail — behind
(#101, Codex review of #251).

A confirmation task loads its subscriber, pauses, and claims the recipient
afterwards. If the subscriber is purged in between, the claim must find the
record gone (``"gone"``), insert nothing and send nothing. On Postgres the two
really race: the purge locks the record ``FOR UPDATE`` before deleting its
claims, the claim holds a share lock while it inserts, so whichever commits
first, no claim row survives the purge.
"""

from __future__ import annotations

import asyncio

import pytest
from sm_records import events
from sm_records.models import RecordType, SubmissionDelivery, tables_for
from sm_records.public_submissions import delivery, sending
from sm_records.services._forget_deliveries import forget_deliveries
from sm_records.services.records import get_record
from sm_records.settings import RecordsSettings
from sm_records.tenancy import tenant_scope
from sqlalchemy import delete, select, text

from tests.app_harness import ADMIN, roles
from tests.newsletter_http import LIST, signup, subscriber
from tests.pg_support import USING_POSTGRES

pytestmark = pytest.mark.unbound_tenant


class Due:
    def __init__(self, uuid: str) -> None:
        self.tenant_id, self.type_key, self.uuid = "default", LIST, uuid
        self.base_url, self.locale, self.attempt = "https://site.example", "en", "race-attempt"


async def _claims(site) -> list:
    async with site.db_state.session_factory() as session:
        with tenant_scope("default"):
            stmt = select(SubmissionDelivery).where(SubmissionDelivery.tenant_id == "default")
            return list((await session.execute(stmt)).scalars())


async def _purge(site, uuid: str) -> None:
    base = f"/api/records/types/{LIST}/records/{uuid}"
    assert (await site.delete(base, headers=roles(ADMIN))).status_code in (200, 204)
    assert (await site.delete(f"{base}/purge", headers=roles(ADMIN))).status_code == 204


async def test_a_task_that_loaded_before_the_purge_sends_and_claims_nothing(newsletter):
    await signup(newsletter)
    sent_before = len(newsletter.outbox.sent)
    uuid = (await subscriber(newsletter))["uuid"]
    async with newsletter.db_state.session_factory() as session:
        with tenant_scope("default"):
            stmt = select(RecordType).where(RecordType.key == LIST)
            rtype = (await session.execute(stmt)).scalar_one()
            record = await get_record(session, rtype, uuid)  # loaded, then "paused"
            await _purge(newsletter, uuid)
            await delivery_claims_cleared(newsletter)
            mail = newsletter.outbox.sent[0]
            await sending.send_all(
                session,
                rtype,
                record,
                newsletter.outbox,
                Due(uuid),
                RecordsSettings(),
                newsletter.db_state.session_factory,
                [("h:erased", mail)],
                lambda: {"sm_confirm_sent_at": None},
            )
    assert len(newsletter.outbox.sent) == sent_before, "the erased address is not mailed"
    assert await _claims(newsletter) == []


async def delivery_claims_cleared(site) -> None:
    assert await _claims(site) == [], "the purge took the signup's claim with it"


async def _fixture(site) -> tuple[RecordType, str, delivery.Slot]:
    await signup(site)
    uuid = (await subscriber(site))["uuid"]
    async with site.db_state.session_factory() as session:
        with tenant_scope("default"):
            await session.execute(delete(SubmissionDelivery))
            await events.commit(session)
            stmt = select(RecordType).where(RecordType.key == LIST)
            rtype = (await session.execute(stmt)).scalar_one()
    return rtype, uuid, delivery.Slot("default", uuid, "race-attempt", "h:subscriber")


async def _locked_purge(site, rtype: RecordType, uuid: str):
    """A purge's first half, uncommitted: the record locked, its claims and
    its row deleted. Returns the open session."""
    cls = tables_for(rtype).record
    session = site.db_state.session_factory()
    uuids = select(cls.uuid).where(cls.uuid == uuid, cls.tenant_id == "default")
    await forget_deliveries(session, "default", uuids, lock=cls.uuid == uuid, table=cls)
    await session.execute(
        text(f"DELETE FROM {cls.__tablename__} WHERE uuid = :u AND tenant_id = 'default'"),
        {"u": uuid},
    )
    return session


@pytest.mark.skipif(not USING_POSTGRES, reason="row locks need two real transactions")
async def test_a_claim_waiting_on_a_purge_finds_the_record_gone(newsletter):
    rtype, uuid, slot = await _fixture(newsletter)
    table = tables_for(rtype).record
    factory = newsletter.db_state.session_factory
    with tenant_scope("default"):
        purge = await _locked_purge(newsletter, rtype, uuid)
        claim = asyncio.create_task(delivery.claim(factory, slot, table))
        await asyncio.sleep(0.5)
        assert not claim.done(), "the claim waits on the purge's row lock"
        await purge.commit()
        await purge.close()
        assert (await asyncio.wait_for(claim, timeout=10))[0] == "gone"
    assert await _claims(newsletter) == []


@pytest.mark.skipif(not USING_POSTGRES, reason="row locks need two real transactions")
async def test_a_claim_made_first_is_deleted_by_the_purge(newsletter):
    rtype, uuid, slot = await _fixture(newsletter)
    table = tables_for(rtype).record
    with tenant_scope("default"):
        assert (await delivery.claim(newsletter.db_state.session_factory, slot, table))[0] == (
            "claimed"
        )
        purge = await _locked_purge(newsletter, rtype, uuid)
        await purge.commit()
        await purge.close()
    assert await _claims(newsletter) == []
