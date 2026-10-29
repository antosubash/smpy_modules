"""The settlement outbox under interleavings: claims, the rehold state machine,
the release dependency, and the janitor's sweep.

Every interleaving is forced through ``billing_settle.HOOK`` (no sleeps): a
second settler run at a chosen step, a worker "crash" (a ``BaseException``
nothing may swallow) at a chosen step, a hold lapsing at a chosen step.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images import billing_ops, billing_settle
from sm_images.janitor import janitor_tenant
from sm_images.models import BillingOp
from sm_images.tenancy import DEFAULT_TENANT

from tests.billing_support import lapsed_image, ops
from tests.pipeline_support import Blur, use_steps

T = DEFAULT_TENANT
LATER = timedelta(hours=2)


class Crash(BaseException):
    """A worker killed mid-settlement."""


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


def _settle(pipe, at: timedelta = LATER):
    return billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + at)


def _rehold_keys(gauge) -> list[str]:
    return sorted(k for k in gauge.keys if "rehold-" in k)


async def _assert_one_live_replacement(pipe, gauge, img, seed):
    row = await pipe.row(img)
    assert [h.id for h in gauge.live()] == [row.storage_hold_id]
    assert gauge.holds[row.storage_hold_id].status == "committed"
    assert gauge.holds[row.storage_hold_id].quantity == row.storage_bytes
    assert gauge.holds[seed].status == "released"
    assert all(o.done_at for o in await ops(pipe.db_state))


async def test_p1a_a_second_settler_never_runs_a_claimed_op(pipe, blur, gauge, hooks):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)
    seen = []

    async def race(op):  # while settler 1 holds the op, settler 2 runs
        seen.append(await _settle(pipe))

    hooks["claimed"] = race
    await _settle(pipe)
    assert seen == [0]  # settler 2 found it claimed (and the release waiting on it)
    assert len(_rehold_keys(gauge)) == 1
    assert [c[0] for c in gauge.calls].count("reserve") == 3  # seed, publication, one rehold
    await _assert_one_live_replacement(pipe, gauge, img, seed)


async def test_p1b_a_replacement_lapsing_before_its_commit_gets_a_new_key(pipe, blur, gauge, hooks):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)

    async def lapse(op):
        (key,) = _rehold_keys(gauge)
        gauge.expire(gauge.keys[key])

    hooks["rehold.persisted"] = lapse
    await _settle(pipe)
    first, second = _rehold_keys(gauge)
    assert (first.endswith("-0"), second.endswith("-1")) == (True, True)
    assert gauge.holds[gauge.keys[first]].status == "expired"  # its key is never reused
    assert (await pipe.row(img)).storage_hold_id == gauge.keys[second]
    await _assert_one_live_replacement(pipe, gauge, img, seed)


@pytest.mark.parametrize("point", ["rehold.reserved", "rehold.persisted", "rehold.committed"])
async def test_p1c_a_crash_mid_rehold_resumes_without_an_orphan(pipe, blur, gauge, hooks, point):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)

    async def crash(op):
        raise Crash()

    hooks[point] = crash
    with pytest.raises(Crash):
        await _settle(pipe)
    assert await _settle(pipe) == 0  # the dead settler's claim still holds
    await _settle(pipe, LATER + billing_settle.CLAIM)  # claim expired: resumed
    assert len(_rehold_keys(gauge)) == 1  # the same replacement, no second one
    await _assert_one_live_replacement(pipe, gauge, img, seed)


async def test_p1c_a_replacement_spent_while_unrecorded_moves_to_a_new_key(
    pipe, blur, gauge, hooks
):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)

    async def crash(op):
        raise Crash()

    hooks["rehold.reserved"] = crash
    with pytest.raises(Crash):
        await _settle(pipe)
    (key,) = _rehold_keys(gauge)
    gauge.expire(gauge.keys[key])  # lapsed before anyone recorded it
    await _settle(pipe, LATER + billing_settle.CLAIM)
    assert len(_rehold_keys(gauge)) == 2
    await _assert_one_live_replacement(pipe, gauge, img, seed)


async def test_the_janitor_sweeps_old_done_ops_but_keeps_awaited_ones(pipe, monkeypatch):
    now = datetime.now(UTC)
    old, fresh = now - timedelta(days=30), now - timedelta(hours=1)
    async with pipe.db_state.session_factory() as s:
        rows = [
            BillingOp(op="commit", hold_id="a", done_at=old),
            BillingOp(op="commit", hold_id="b", done_at=old),
            BillingOp(op="commit", hold_id="c", done_at=old),
            BillingOp(op="commit", hold_id="d", done_at=fresh),
            BillingOp(op="commit", hold_id="e", done_at=old),  # awaited below
        ]
        s.add_all(rows)
        await s.flush()
        s.add(BillingOp(op="release", hold_id="f", after_id=rows[4].id))  # pending
        await s.commit()
    monkeypatch.setattr(billing_ops, "SWEEP_BATCH", 1)
    monkeypatch.setattr(billing_ops, "SWEEP_BATCHES", 2)
    assert await billing_ops.sweep(pipe.db_state.session_factory, T, now - timedelta(days=7)) == 2
    done = await janitor_tenant(pipe.runtime, T, now)
    assert done["billing_ops_swept"] == 1  # bounded per call; the rest next time
    assert sorted(o.hold_id for o in await ops(pipe.db_state)) == ["d", "e", "f"]
