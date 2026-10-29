"""Rehold recovery at the release and swap commit boundaries (round 4).

* A rehold that dies after its replacement's ref committed ``released``, but
  before it advanced the generation, resumes: the released ref counts as a
  release that succeeded.
* A replacement a takeover committed but could not install (a stale settler
  won its release, then died before calling billing) is released, exactly
  once, through a durable outbox op.
* Nothing in ``sm_images`` reads a hold without naming its tenant.

Interleavings are forced through ``billing_settle.HOOK``; a "crash" is a
``BaseException`` nothing may swallow.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sm_images import billing_ops
from sm_images.models import BillingOp
from sm_images.models.hold_ref import HoldRef
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.billing_support import lapsed_image, ops
from tests.pipeline_support import Blur, use_steps

T = DEFAULT_TENANT
LATER = timedelta(hours=2)
RETRY = LATER + timedelta(minutes=10)  # past the dead settler's claim


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


def _rehold_hold(gauge, generation: int) -> str:
    (key,) = [k for k in gauge.keys if k.endswith(f"-{generation}") and "rehold-" in k]
    return gauge.keys[key]


async def _stall(pipe, op) -> None:
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(BillingOp)
            .where(BillingOp.id == op.id)
            .values(claim_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()


async def _crash(op):
    raise Crash()


async def test_a_crash_after_the_release_committed_resumes(pipe, blur, gauge, hooks):
    """The replacement lapses; its release commits ``released``; the settler
    dies before advancing the generation. The retry must not wedge."""
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)

    async def lapse(op):
        gauge.expire(_rehold_hold(gauge, 0))

    hooks["rehold.persisted"] = lapse
    hooks["rehold.spent"] = _crash
    with pytest.raises(Crash):
        await _settle(pipe)
    first = _rehold_hold(gauge, 0)
    assert (await _refs(pipe))[first] == "released"
    await _settle(pipe, RETRY)
    second = _rehold_hold(gauge, 1)
    assert (await pipe.row(img)).storage_hold_id == second
    assert gauge.holds[second].status == "committed"
    assert gauge.holds[seed].status == "released"
    assert [h.id for h in gauge.live()] == [second]
    assert all(o.done_at for o in await ops(pipe.db_state))


async def test_a_replacement_whose_swap_lost_is_released_once(pipe, blur, gauge, hooks):
    """Stale settler A wins the replacement's release and dies before calling
    billing. Takeover B, still reading it held, commits it, loses the install
    CAS and moves on: the committed replacement must still be released."""
    coll = await pipe.collection({"acme.blur": {}})
    img, seed, _ = await lapsed_image(pipe, gauge, coll)

    async def stale(op):
        gauge.lie_expired.add(_rehold_hold(gauge, 0))  # A reads it expired

    async def takeover_then_die(op):  # A has won the ref, billing not called
        await _stall(pipe, op)
        await _settle(pipe)  # settler B
        raise Crash()  # A never reaches billing

    hooks["rehold.persisted"] = stale
    hooks["rehold.releasing"] = takeover_then_die
    with pytest.raises(Crash):
        await _settle(pipe)
    await _settle(pipe, RETRY)  # reconcile: anything still due
    first, second = _rehold_hold(gauge, 0), _rehold_hold(gauge, 1)
    assert (await pipe.row(img)).storage_hold_id == second
    assert gauge.holds[first].status == "released"
    assert gauge.calls.count(("release", first)) == 1
    refs = await _refs(pipe)
    assert (refs[first], refs[second]) == ("released", "installed")
    assert gauge.holds[seed].status == "released"
    assert [h.id for h in gauge.live()] == [second]
    assert all(o.done_at for o in await ops(pipe.db_state))


async def test_a_lost_swap_records_the_release_with_the_generation(pipe, blur, gauge, hooks):
    """B crashes right after its lost swap is recorded: the replacement's
    release op is already durable, in that same transaction."""
    coll = await pipe.collection({"acme.blur": {}})
    _, _, _ = await lapsed_image(pipe, gauge, coll)
    seen = {}

    async def stale(op):
        gauge.lie_expired.add(_rehold_hold(gauge, 0))

    async def takeover(op):
        hooks["rehold.swap_lost"] = record_then_die
        await _stall(pipe, op)
        with pytest.raises(Crash):
            await _settle(pipe)
        raise Crash()

    async def record_then_die(op):
        rows = await ops(pipe.db_state)
        seen["gen"] = next(o.generation for o in rows if o.op == "rehold")
        seen["release"] = [o.hold_id for o in rows if o.op == "release"]
        raise Crash()

    hooks["rehold.persisted"] = stale
    hooks["rehold.releasing"] = takeover
    with pytest.raises(Crash):
        await _settle(pipe)
    first = _rehold_hold(gauge, 0)
    assert seen["gen"] == 1
    assert first in seen["release"]
    await _settle(pipe, RETRY)
    await _settle(pipe, RETRY + RETRY)
    assert gauge.holds[first].status == "released"
    assert gauge.calls.count(("release", first)) == 1
    assert all(o.done_at for o in await ops(pipe.db_state))


def test_every_hold_read_names_its_tenant():
    """``UsageMeter.get_hold(tenant_id, hold_id)``: a one-argument call is the
    old signature, which billing no longer accepts."""
    root = Path(__file__).resolve().parents[1] / "sm_images"
    bad = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_hold"
                and len(node.args) + len(node.keywords) != 2
            ):
                bad.append(f"{path.name}:{node.lineno}")
    assert bad == []
