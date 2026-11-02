"""Settle, install and repair replay the subject an op recorded (#284).

Billing scopes keys and holds to a subject: ``swap`` raises ``HoldNotFound``
for another subject's old hold, ``get_hold`` answers ``None`` and
``close_key`` answers ``Closed`` (leaving the real key open). The fake gauge
does the same, so each test here fails if the op layer asked under any
subject other than the one the hold or key was made under.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sm_images.core import billing
from sm_images.core.billing import ops as billing_ops
from sm_images.core.billing import repair as billing_repair
from sm_images.core.billing.settle import BILLING_OP_MAX_AGE, CLAIM, OP_EXPIRED
from sm_images.core.tenancy import DEFAULT_TENANT as T
from sm_images.models import BillingOp, Collection, Image
from sm_images.models.billing_op import OP_SWAP
from sqlalchemy import update

from tests.support.billing import assert_counted_once, held_image, ops


def _user() -> str:
    return f"user:{uuid.uuid4()}"


def _settle(pipe, at: timedelta = CLAIM + timedelta(seconds=1)):
    return billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + at)


async def _queue(pipe, img, qty: int, subject: str | None) -> BillingOp:
    """The image now stores ``qty``; a swap to it queued under ``subject``
    (``None``: a row written before #284)."""
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Image).where(Image.id == img).values(storage_bytes=qty))
        if subject is None:
            row = BillingOp(op=OP_SWAP, image_id=img, quantity=qty, idempotency_key="legacy")
            s.add(row)
            await s.flush()
        else:
            row = await billing_ops.add_swap(s, img, qty, subject=subject)
        await s.commit()  # not finalize_session: the test settles when it chooses
    return row


async def _no_settle(*args, **kwargs) -> int:
    return 0


async def _done(pipe, img, hold_id, qty, key, subject, **kw) -> None:
    """A done ``swap`` op the repair has yet to examine."""
    async with pipe.db_state.session_factory() as s:
        s.add(
            BillingOp(
                op=OP_SWAP,
                image_id=img,
                hold_id=hold_id,
                quantity=qty,
                idempotency_key=key,
                subject=subject,
                done_at=datetime.now(UTC),
                **kw,
            )
        )
        await s.commit()


def _new_hold(gauge, seed):
    (hold,) = [h for h in gauge.live() if h.id != seed]
    return hold


async def test_legacy_null_subject_op_settles_under_tenant(pipe, gauge):
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)
    await _queue(pipe, img, 5000, None)
    await _settle(pipe)
    assert _new_hold(gauge, seed).tenant_id == T
    assert (await pipe.row(img)).storage_subject == T  # the billed subject, recorded
    await assert_counted_once(pipe.db_state, gauge)


async def test_user_subject_swap_settles_under_user(pipe, gauge):
    who = _user()
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll, subject=who)
    await _queue(pipe, img, 5000, who)
    await _settle(pipe)
    hold = _new_hold(gauge, seed)
    assert (hold.tenant_id, hold.quantity) == (who, 5000)
    row = await pipe.row(img)
    assert (row.storage_hold_id, row.storage_subject) == (hold.id, who)
    assert gauge.level_of(T) == 0
    await assert_counted_once(pipe.db_state, gauge)


async def test_queued_swap_fixes_subject_with_old_hold(pipe, gauge):
    """Review focus 1: queued under ``default``, but the image's hold is now
    the user's. The swap must name that hold under its subject - not raise
    ``HoldNotFound`` and back off forever."""
    who = _user()
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll, subject=who)
    queued = await _queue(pipe, img, 5000, T)
    await _settle(pipe)
    (op,) = [o for o in await ops(pipe.db_state) if o.id == queued.id]
    assert (op.subject, op.old_hold_id, op.last_error) == (who, seed, None)
    assert op.done_at is not None
    assert _new_hold(gauge, seed).tenant_id == who
    await assert_counted_once(pipe.db_state, gauge)


async def test_queued_swap_on_an_image_with_no_hold_keeps_its_subject(pipe, gauge):
    who = _user()
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    queued = await _queue(pipe, img, 5000, who)
    await _settle(pipe)
    (op,) = [o for o in await ops(pipe.db_state) if o.id == queued.id]
    assert op.subject == who
    (hold,) = gauge.live()
    assert hold.tenant_id == who
    assert (await pipe.row(img)).storage_subject == who
    await assert_counted_once(pipe.db_state, gauge)


async def test_expired_user_op_closes_key_under_its_subject(pipe, gauge):
    """Review focus 2: the swap reached billing (a hold under the user) but
    images never heard. The expiry's ``close_key`` must ask under the user:
    under the tenant billing would answer ``Closed`` and the hold be lost."""
    who = _user()
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll, subject=who)
    queued = await _queue(pipe, img, 5000, who)
    made = await gauge.swap(
        who, billing.METER, seed, 5000, queued.idempotency_key, source=billing.SOURCE
    )
    await _settle(pipe, BILLING_OP_MAX_AGE + timedelta(hours=1))
    assert ("close_key", who, queued.idempotency_key) in gauge.calls
    assert not [c for c in gauge.calls if c[0] == "close_key" and c[1] != who]
    (op,) = [o for o in await ops(pipe.db_state) if o.id == queued.id]
    assert op.hold_id == made.id  # billing's answer: the hold the key made
    assert await billing_repair.repair(pipe.db_state.session_factory, T) == 1
    row = await pipe.row(img)
    assert (row.storage_hold_id, row.storage_subject) == (made.id, who)
    await assert_counted_once(pipe.db_state, gauge)


async def test_repair_reads_holds_under_their_subjects(pipe, gauge):
    """Review focus 2: a done user op whose hold the image names, at the right
    size. Read under the tenant, ``get_hold`` would answer ``None`` and the
    repair queue a second hold."""
    who = _user()
    coll = await pipe.collection({})
    img, _seed = await held_image(pipe, gauge, coll, subject=who)
    await _queue(pipe, img, 5000, who)
    await _settle(pipe)
    before = len(await ops(pipe.db_state))
    calls = len(gauge.calls)
    assert await billing_repair.repair(pipe.db_state.session_factory, T) == 0
    assert len(await ops(pipe.db_state)) == before
    reads = [c for c in gauge.calls[calls:] if c[0] == "get_hold"]
    assert reads and all(c[1] == who for c in reads)
    await assert_counted_once(pipe.db_state, gauge)


async def test_repair_closes_an_expired_key_under_its_subject(pipe, gauge):
    """An op expired with no outcome recorded: the repair's ``close_key`` asks
    under the op's subject, finds the hold its swap made and installs it."""
    who = _user()
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll, subject=who)
    size = (await pipe.row(img)).storage_bytes
    made = await gauge.swap(who, billing.METER, seed, size, "late", source=billing.SOURCE)
    await _done(pipe, img, None, size, "late", who, last_error=OP_EXPIRED)
    assert await billing_repair.repair(pipe.db_state.session_factory, T) == 1
    assert ("close_key", who, "late") in gauge.calls
    row = await pipe.row(img)
    assert (row.storage_hold_id, row.storage_subject) == (made.id, who)
    await assert_counted_once(pipe.db_state, gauge)


async def test_repair_installs_orphan_with_its_subject(pipe, gauge, monkeypatch):
    """A lost swap under the user, on an image whose named hold is a legacy
    tenant hold that no longer counts: the orphan is read under the op's
    subject, installed with it, and the correcting swap runs under it."""
    who = _user()
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll)  # legacy: NULL subject
    size = (await pipe.row(img)).storage_bytes
    await gauge.release(seed)
    orphan = await gauge.swap(who, billing.METER, None, size - 1, "lost", source=billing.SOURCE)
    await _done(pipe, img, orphan.id, size - 1, "lost", who)
    factory = pipe.db_state.session_factory
    with monkeypatch.context() as later:  # the correction waits: read it as written
        later.setattr(billing_ops, "settle", _no_settle)
        assert await billing_repair.repair(factory, T) == 1
    (fix,) = [o for o in await ops(pipe.db_state) if o.done_at is None]
    assert (fix.quantity, fix.subject) == (size, who)
    await _settle(pipe)
    row = await pipe.row(img)
    assert row.storage_subject == who
    assert gauge.holds[row.storage_hold_id].tenant_id == who
    assert gauge.holds[orphan.id].status == "released"  # replaced by the correction
    assert next(c for c in gauge.calls if c[0] == "get_hold" and c[2] == orphan.id)[1] == who
    await assert_counted_once(pipe.db_state, gauge)


async def test_user_hold_survives_owner_change(pipe, gauge):
    a, b = uuid.uuid4(), uuid.uuid4()
    coll = await pipe.collection({})
    img, seed = await held_image(pipe, gauge, coll, subject=f"user:{a}")
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Collection).where(Collection.id == coll.id).values(owner_id=str(b)))
        await s.commit()
    await _queue(pipe, img, 5000, f"user:{a}")
    await _settle(pipe)
    assert _new_hold(gauge, seed).tenant_id == f"user:{a}"
    assert gauge.level_of(f"user:{b}") == 0
    await assert_counted_once(pipe.db_state, gauge)
