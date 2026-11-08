"""``lock_confirmation`` and the row lock every unsubscribe takes (newsletter PR 6, C2).

Newsletter's suppression lift asks records whether the address confirmed
after an opt-out, and the answer has to hold until the lift commits: the
subscriber's row is locked, and every unsubscribe (``opt_in.leave``) takes the
same lock before it decides. The waiting tests need two real transactions, so
they run on Postgres only.
"""

from __future__ import annotations

import asyncio

import pytest
from sm_records.contracts.newsletter import iter_subscribers
from sm_records.contracts.newsletter_admin import ConfirmProof, lock_confirmation
from sm_records.core import events
from sm_records.core.settings import RecordsSettings

from tests.pg_support import USING_POSTGRES
from tests.support.app_harness import ADMIN, roles
from tests.support.newsletter_contract import TENANT, seed_list, session, unbound, uuid_of
from tests.support.newsletter_http import LIST

ADA = "ada@example.org"
pg_only = pytest.mark.skipif(not USING_POSTGRES, reason="two real transactions need Postgres")


async def _proof(client, email: str, *, tenant: str = TENANT, type_key: str = LIST):
    async with session(client) as db:
        proof = await lock_confirmation(db, tenant_id=tenant, type_key=type_key, email=email)
        await db.rollback()
    return proof


async def _confirmed_at(client, email: str):
    async with session(client) as db:
        hits, _ = await iter_subscribers(db, tenant_id=TENANT, type_key=LIST, status="confirmed")
    return next(h.confirmed_at for h in hits if h.email == email)


async def test_lock_confirmation_proof_for_confirmed_only(audience):
    proof = await _proof(audience, "  ADA@Example.org ")
    assert isinstance(proof, ConfirmProof)
    assert proof.uuid == await uuid_of(audience, ADA)
    assert proof.confirmed_at == await _confirmed_at(audience, ADA)
    assert await _proof(audience, "cy@example.org") is None  # pending
    assert await _proof(audience, "nobody@example.org") is None
    bob = await uuid_of(audience, "bob@example.org")
    gone = await audience.delete(f"/api/records/types/{LIST}/records/{bob}", headers=roles(ADMIN))
    assert gone.status_code < 300
    assert await _proof(audience, "bob@example.org") is None  # trashed


async def test_lock_confirmation_pins_tenant_and_list(audience):
    with unbound():
        other = await seed_list(audience.db_state, "other", "eve@example.org")
    assert await _proof(audience, ADA, type_key="nope") is None
    assert await _proof(audience, "eve@example.org") is None
    with unbound():
        assert await _proof(audience, ADA, tenant="other") is None
        theirs = await _proof(audience, "eve@example.org", tenant="other")
    assert theirs is not None and theirs.uuid == other


async def test_lock_confirmation_row_purged_before_the_lock(audience, monkeypatch):
    """A purge landing between the find and the lock answers ``None``, not a 500."""
    from sm_records.contracts import newsletter_admin
    from sm_records.public_submissions.row_lock import lock_record

    async def purged(db, rtype, record):
        gone = type(record)(id=-1, tenant_id=record.tenant_id)
        return await lock_record(db, rtype, gone)

    monkeypatch.setattr(newsletter_admin, "lock_record", purged)
    assert await _proof(audience, ADA) is None


async def _unsubscribe(db, uuid: str) -> bool:
    from sm_records.contracts.newsletter import unsubscribe

    return await unsubscribe(
        db,
        tenant_id=TENANT,
        type_key=LIST,
        uuid=uuid,
        unless_confirmed_after=None,
        settings=RecordsSettings(),
    )


async def test_unsubscribe_of_a_row_purged_before_the_lock(audience, monkeypatch):
    """A purge landing between the contract's lookup and leave's lock answers
    ``False`` (nothing written), not ``NoResultFound``."""
    from sm_records.public_submissions import transition
    from sm_records.public_submissions.row_lock import lock_record

    async def purged(db, rtype, record):
        return await lock_record(db, rtype, type(record)(id=-1, tenant_id=record.tenant_id))

    monkeypatch.setattr(transition, "lock_record", purged)
    uuid = await uuid_of(audience, ADA)
    async with session(audience) as db:
        assert await _unsubscribe(db, uuid) is False
        await db.rollback()


@pg_only
async def test_unsubscribe_waits_for_a_held_lock(audience):
    uuid = await uuid_of(audience, ADA)
    async with session(audience) as first, session(audience) as second:
        assert await lock_confirmation(first, tenant_id=TENANT, type_key=LIST, email=ADA)

        async def leave() -> bool:
            wrote = await _unsubscribe(second, uuid)
            await events.commit(second)
            return wrote

        task = asyncio.create_task(leave())
        await asyncio.sleep(0.3)
        assert not task.done()
        await first.commit()
        assert await asyncio.wait_for(task, 10) is True


@pg_only
async def test_leave_locks_before_deciding(audience):
    uuid = await uuid_of(audience, ADA)
    async with session(audience) as first, session(audience) as second:
        assert await _unsubscribe(first, uuid) is True

        async def ask():
            proof = await lock_confirmation(second, tenant_id=TENANT, type_key=LIST, email=ADA)
            await second.rollback()
            return proof

        task = asyncio.create_task(ask())
        await asyncio.sleep(0.3)
        assert not task.done()
        await events.commit(first)
        assert await asyncio.wait_for(task, 10) is None
