"""No waits-for cycle through the quota (round 5).

A release op may wait for the image's current hold to be committed - but a
commit that needs fresh quota (a rehold) must never wait, through the quota,
on a release that waits for it.

* Codex's trace: O's release waits on H; H's rehold commits R, the image
  moves on to N before the swap; N lapses and D fills the quota
  (O + R + D = limit); N's rehold is refused. R (never installed) must be
  released at once, so N's rehold fits, and then O is released.
* The same cycle through O alone: the image's current hold lapsed and its
  rehold is refused for quota while O, waiting on it, holds the room.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images import billing, billing_ops, hold_refs
from sm_images.models import BillingOp, Image
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

from tests.billing_support import lapsed_image, ops
from tests.pipeline_support import Blur, use_steps

T = DEFAULT_TENANT
LATER = timedelta(hours=2)
FAR = timedelta(days=2)  # N's own commit op is first due here


@pytest.fixture
def blur():
    step = Blur()
    use_steps(step)
    return step


def _settle(pipe, at: timedelta = LATER):
    return billing_ops.settle(pipe.db_state.session_factory, T, now=datetime.now(UTC) + at)


def _rehold_holds(gauge) -> list[str]:
    return [gauge.keys[k] for k in sorted(gauge.keys) if "rehold-" in k]


async def _fill(gauge, room: int = 0) -> str:
    """D: another image's committed hold; the limit leaves ``room`` free."""
    d = await gauge.reserve(T, billing.METER, 1, "D", source="t")
    await gauge.commit(d.id)
    gauge.limit = gauge.level + room
    return d.id


async def test_codex_trace_a_moved_on_replacement_never_waits(pipe, blur, gauge, hooks):
    coll = await pipe.collection({"acme.blur": {}})
    img, o, h = await lapsed_image(pipe, gauge, coll)
    seen = {}

    async def move_on(op):  # R is committed; before the swap the image moves to N
        (r,) = _rehold_holds(gauge)
        total = gauge.holds[r].quantity
        n = await gauge.reserve(T, billing.METER, total, "N", source="t")
        gauge.expire(n.id)  # N lapses before its commit
        async with pipe.db_state.session_factory() as s:
            await s.execute(update(Image).where(Image.id == img).values(storage_hold_id=n.id))
            await hold_refs.installed(s, n.id, img)
            await hold_refs.orphan(s, T, h)
            first = BillingOp(
                op="commit",
                image_id=img,
                hold_id=n.id,
                quantity=total,
                next_attempt_at=datetime.now(UTC) + FAR,
            )
            s.add(first)
            await s.flush()
            s.add(BillingOp(op="release", image_id=img, hold_id=h, after_id=first.id))
            await s.commit()
        seen.update(r=r, n=n.id, d=await _fill(gauge))  # O + R + D = limit

    hooks["rehold.committed"] = move_on
    await _settle(pipe)  # H's rehold: moved on, so R is spare
    r, n, d = seen["r"], seen["n"], seen["d"]
    assert gauge.holds[r].status == "released"  # due at once, not behind N
    for k in range(4):  # N's rehold, then whatever waited on it
        await _settle(pipe, FAR + LATER * (k + 1))
    row = await pipe.row(img)
    assert row.storage_hold_id not in (o, h, n, r)
    assert gauge.holds[row.storage_hold_id].status == "committed"
    assert gauge.holds[o].status == "released"
    assert sorted(x.id for x in gauge.live()) == sorted([row.storage_hold_id, d])
    assert all(x.done_at for x in await ops(pipe.db_state))


async def test_a_release_never_waits_on_a_rehold_refused_for_quota(pipe, blur, gauge):
    """O waits on H's rehold; the rehold needs O's room. O must give way."""
    coll = await pipe.collection({"acme.blur": {}})
    img, o, h = await lapsed_image(pipe, gauge, coll)
    total = sum(x.quantity for x in gauge.holds.values() if x.id == h)
    d = await _fill(gauge, room=total - 1)  # fits only once O is released
    for k in range(4):
        await _settle(pipe, LATER * (k + 1) * 4)
    row = await pipe.row(img)
    assert row.storage_hold_id not in (o, h)
    assert gauge.holds[row.storage_hold_id].status == "committed"
    assert gauge.holds[o].status == "released"
    assert sorted(x.id for x in gauge.live()) == sorted([row.storage_hold_id, d])
    assert all(x.done_at for x in await ops(pipe.db_state))


async def test_a_release_still_waits_on_a_held_current_hold(pipe, blur, gauge):
    """The healthy path keeps its order: a current hold that is merely held
    (its commit needs no quota) is waited for."""
    coll = await pipe.collection({"acme.blur": {}})
    img, o, _ = await lapsed_image(pipe, gauge, coll)
    (rehold,) = [x for x in await ops(pipe.db_state) if x.op == "commit"]
    held = await gauge.reserve(T, billing.METER, 1, "C", source="t")
    gauge.refuse_commit = {held.id}  # C stays held
    gauge.limit = gauge.level  # any rehold would be refused
    async with pipe.db_state.session_factory() as s:
        await s.execute(update(Image).where(Image.id == img).values(storage_hold_id=held.id))
        await s.execute(
            update(BillingOp).where(BillingOp.id == rehold.id).values(done_at=datetime.now(UTC))
        )
        await s.commit()
    await _settle(pipe)
    assert gauge.holds[o].status == "committed"
