"""Hold ownership (``images_hold_ref``) and the outbox's fairness.

* A stale settler releasing a replacement and a takeover settler installing it
  can never both win - in either order.
* Releases waiting on their image's current hold never starve the commits
  behind them.
* A replacement billing no longer knows counts as released: recovery moves on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images import billing_ops
from sm_images.models import BillingOp, Image
from sm_images.models.hold_ref import HoldRef
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.billing_support import held_image, lapsed_image, ops
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


async def _refs(pipe) -> dict[str, str]:
    async with pipe.db_state.session_factory() as s:
        return dict((await s.execute(select(HoldRef.hold_id, HoldRef.state))).all())


async def _stall(pipe, op) -> None:
    """Settler A's claim lapses while it is stalled: B may take the op over."""
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(BillingOp)
            .where(BillingOp.id == op.id)
            .values(claim_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()


def _rehold_hold(gauge, generation: int) -> str:
    (key,) = [k for k in gauge.keys if k.endswith(f"-{generation}") and "rehold-" in k]
    return gauge.keys[key]


async def test_a_publication_installs_its_hold_and_orphans_the_old(pipe, blur, gauge):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed = await held_image(pipe, gauge, coll)
    await pipe.run(img)
    new = (await pipe.row(img)).storage_hold_id
    assert (await _refs(pipe))[new] == "installed"
    assert (await _refs(pipe)).get(seed) == "released"  # never installed by a ref: claimed


async def test_a_takeovers_swap_first_then_the_stale_release_loses(pipe, blur, gauge, hooks):
    """B installs the replacement; stalled A then reads it expired and tries to
    release it: A must not."""
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)

    async def takeover(op):
        await _stall(pipe, op)
        await _settle(pipe)  # settler B: resumes the recorded replacement and swaps it
        gauge.lie_expired.add(_rehold_hold(gauge, 0))  # A's stale view of it

    hooks["rehold.persisted"] = takeover
    await _settle(pipe)  # settler A
    replacement = _rehold_hold(gauge, 0)
    assert (await pipe.row(img)).storage_hold_id == replacement
    assert gauge.holds[replacement].status == "committed"  # not released by A
    assert (await _refs(pipe))[replacement] == "installed"
    assert gauge.holds[seed].status == "released"
    assert [h.id for h in gauge.live()] == [replacement]


async def test_a_stale_release_first_then_the_takeovers_swap_loses(pipe, blur, gauge, hooks):
    """A wins the replacement's release; B (still seeing it held) commits it
    but cannot install it, and moves to a new generation."""
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)

    async def stale(op):
        gauge.lie_expired.add(_rehold_hold(gauge, 0))  # A reads it expired

    async def takeover(op):  # A has won the release, billing not called yet
        await _stall(pipe, op)
        await _settle(pipe)

    hooks["rehold.persisted"] = stale
    hooks["rehold.releasing"] = takeover
    await _settle(pipe)
    first, second = _rehold_hold(gauge, 0), _rehold_hold(gauge, 1)
    assert gauge.holds[first].status == "released"
    assert (await pipe.row(img)).storage_hold_id == second
    assert gauge.holds[second].status == "committed"
    refs = await _refs(pipe)
    assert (refs[first], refs[second]) == ("released", "installed")
    assert gauge.holds[seed].status == "released"
    assert [h.id for h in gauge.live()] == [second]


async def test_waiting_releases_never_starve_the_commits_behind_them(pipe, gauge):
    """150 releases (more than a page) wait for the image's current hold, whose
    commit was written after them."""
    img = uuid.uuid4()
    current = await gauge.reserve(T, "images.storage_bytes", 5, "current", source="t")
    olds = []
    for n in range(150):
        hold = await gauge.reserve(T, "images.storage_bytes", 1, f"old-{n}", source="t")
        await gauge.commit(hold.id)
        olds.append(hold.id)
    coll = await pipe.collection({})
    async with pipe.db_state.session_factory() as s:
        s.add(
            Image(
                id=img,
                collection_id=coll.id,
                storage_key="k",
                filename="a.jpg",
                content_type="image/jpeg",
                size_bytes=5,
                storage_hold_id=current.id,
            )
        )
        s.add_all(BillingOp(op="release", image_id=img, hold_id=h) for h in olds)
        await s.flush()
        s.add(BillingOp(op="commit", image_id=img, hold_id=current.id, quantity=5))
        await s.commit()
    await _settle(pipe, timedelta(0))
    assert gauge.holds[current.id].status == "committed"
    assert all(gauge.holds[h].status == "released" for h in olds)
    assert all(o.done_at for o in await ops(pipe.db_state))


async def test_a_replacement_billing_lost_is_treated_as_released(pipe, blur, gauge, hooks):
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)

    async def crash(op):
        raise Crash()

    hooks["rehold.persisted"] = crash
    with pytest.raises(Crash):
        await _settle(pipe)
    gauge.forget(_rehold_hold(gauge, 0))  # billing purged it
    await _settle(pipe, LATER + timedelta(minutes=10))  # one pass, no backoff loop
    second = _rehold_hold(gauge, 1)
    assert (await pipe.row(img)).storage_hold_id == second
    assert gauge.holds[second].status == "committed"
    assert gauge.holds[seed].status == "released"
    # Done in that one pass: no failure was counted (the 1 is the setup's commit).
    assert [(o.op, bool(o.done_at), o.attempts) for o in await ops(pipe.db_state)][:2] == [
        ("rehold", True, 1),
        ("release", True, 0),
    ]
