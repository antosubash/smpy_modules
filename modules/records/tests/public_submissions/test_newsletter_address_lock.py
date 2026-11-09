"""The per-address opt-out lock (newsletter PR 7, Codex finding 1).

Every unsubscribe (``opt_in.leave``) and newsletter's import batch
(``lock_import_batch``) take ``pg_advisory_xact_lock`` on one key per
(tenant, address) before any type or row lock, so an opt-out on one list
cannot land between the import's "unsubscribed anywhere?" read and its create
on another. The waiting tests need two real transactions: Postgres only.
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from sm_records.core import events
from sm_records.core.settings import RecordsSettings

from tests.pg_support import USING_POSTGRES
from tests.support.newsletter_contract import TENANT, session, unbound, uuid_of
from tests.support.newsletter_http import LIST
from tests.support.newsletter_import import KEY, make_list

ADA = "ada@example.org"
pg_only = pytest.mark.skipif(not USING_POSTGRES, reason="two real transactions need Postgres")


def test_address_key_is_stable_normalised_and_per_tenant():
    from sm_records.contracts.newsletter_import import address_lock_key, address_lock_key_from_hash

    key = address_lock_key(TENANT, ADA)
    assert -(2**63) <= key < 2**63
    assert address_lock_key(TENANT, "  ADA@Example.org ") == key
    assert address_lock_key("other", ADA) != key
    assert address_lock_key(TENANT, "bob@example.org") != key
    digest = hashlib.sha256(ADA.encode()).hexdigest()  # newsletter's ``email_hash``
    assert address_lock_key_from_hash(TENANT, digest) == key


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


@pg_only
async def test_unsubscribe_waits_for_the_address_lock(audience):
    """Session 1 holds only Ada's address lock (no type or row lock): the
    unsubscribe of her on ``news`` waits for it."""
    from sm_records.public_submissions.address_lock import lock_addresses

    uuid = await uuid_of(audience, ADA)
    async with session(audience) as first, session(audience) as second:
        await lock_addresses(first, TENANT, ["  Ada@Example.org"])

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
async def test_import_batch_lock_waits_for_an_unsubscribe(audience):
    """An unsubscribe of Ada on ``news`` holds her address lock to its commit:
    a batch of another list (``weekly``) naming her waits for it."""
    from sm_records.contracts.newsletter_import import lock_import_batch

    await make_list(audience)
    uuid = await uuid_of(audience, ADA)
    async with session(audience) as first, session(audience) as second:
        assert await _unsubscribe(first, uuid) is True

        async def batch() -> None:
            with unbound():
                await lock_import_batch(
                    second, tenant_id=TENANT, type_key=KEY, emails=["bob@example.org", ADA]
                )
            await second.rollback()

        task = asyncio.create_task(batch())
        await asyncio.sleep(0.3)
        assert not task.done()
        await events.commit(first)
        await asyncio.wait_for(task, 10)


async def test_import_batch_lock_refuses_a_missing_list(audience):
    from sm_records.contracts.newsletter_import import lock_import_batch

    async with session(audience) as db:
        with unbound(), pytest.raises(LookupError):
            await lock_import_batch(db, tenant_id=TENANT, type_key="nope", emails=[ADA])
        with unbound(), pytest.raises(ValueError):
            await lock_import_batch(db, tenant_id=TENANT, type_key=LIST, emails="ada")  # type: ignore[arg-type]
