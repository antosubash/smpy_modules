"""Leases and fences: a slow or stale worker never overwrites a newer result."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sm_images.models import StepRun
from sm_images.pipeline.advance import plan_and_claim
from sm_images.pipeline.claim import complete, lock_image, renew
from sm_images.pipeline.executor import run_step_async
from sm_images.pipeline.step import StepOutcome
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

from tests.support.pipeline import Blur, Scripted, make_pipe, use_steps

T = DEFAULT_TENANT
LEASE = 1800


async def _claim(pipe, img) -> dict[str, uuid.UUID]:
    """Claim what is ready, as a dispatch whose message then got lost."""
    async with pipe.db_state.session_factory() as s:
        found = await plan_and_claim(s, T, img, datetime.now(UTC), LEASE)
        await s.commit()
    return {c.step: c.token for c in found.claims}


async def _expire(pipe, img, step) -> None:
    async with pipe.db_state.session_factory() as s:
        past = datetime.now(UTC) - timedelta(seconds=1)
        await s.execute(
            update(StepRun)
            .where(StepRun.image_id == img, StepRun.step == step)
            .values(lease_expires_at=past)
        )
        await s.commit()


async def test_lease_expiry_reclaims(pipe):
    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    old = (await _claim(pipe, img))["acme.x"]
    await pipe.run(img)  # a live lease is left alone
    assert (await pipe.status(img), x.calls) == ({"acme.x": "running"}, 0)

    await _expire(pipe, img, "acme.x")
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.x"]
    assert (run.status.value, run.attempts, x.calls) == ("completed", 2, 1)
    assert await run_step_async(pipe.runtime, T, img, "acme.x", old) is False
    assert x.calls == 1


async def test_stale_lease_cannot_complete_or_publish_display(pipe):
    """Worker A loads under its lease and stalls; the lease expires and worker B
    reclaims, publishes and finishes. A's late result, display copy and
    renditions are all discarded and A's staged object is deleted."""
    blur = Blur()
    gate = asyncio.Event()
    real = blur.run

    async def stalls_once(ctx):
        if blur.calls == 0:
            blur.calls += 1
            await gate.wait()
            await ctx.write_display(b"stale bytes", "image/jpeg")
            return StepOutcome.completed({"stale": True})
        return await real(ctx)

    blur.run = stalls_once
    use_steps(blur)
    coll = await pipe.collection({"acme.blur": {}, "renditions": {}})
    img = await pipe.image(coll)
    token_a = (await _claim(pipe, img))["acme.blur"]
    worker_a = asyncio.ensure_future(run_step_async(pipe.runtime, T, img, "acme.blur", token_a))
    await asyncio.sleep(0.05)
    assert not worker_a.done()

    await _expire(pipe, img, "acme.blur")
    await pipe.run(img)  # worker B
    won = await pipe.row(img)
    assert (won.display_generation, await pipe.status(img)) == (
        1,
        {"acme.blur": "completed", "renditions": "completed"},
    )
    keys_after_b = set(pipe.keys())

    gate.set()
    assert await asyncio.wait_for(worker_a, 10) is False
    row = await pipe.row(img)
    assert (row.display_key, row.display_generation) == (won.display_key, 1)
    run = (await pipe.runs(img))["acme.blur"]
    assert run.output == {"blurred": 1}
    assert set(pipe.keys()) == keys_after_b  # A's staged copy is gone
    assert token_a.hex not in " ".join(pipe.keys())


async def test_complete_needs_an_unexpired_lease(pipe):
    """Token alone is not enough: an expired lease cannot complete, even unclaimed."""
    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    token = (await _claim(pipe, img))["acme.x"]
    await _expire(pipe, img, "acme.x")
    async with pipe.db_state.session_factory() as s:
        now = datetime.now(UTC)
        assert not await renew(s, T, img, "acme.x", token, now, LEASE)
        ok = await complete(s, T, img, "acme.x", token, StepOutcome.completed({}), now, version=1)
        assert ok is False
        assert await renew(s, T, img, "acme.x", uuid.uuid4(), now, LEASE) is False


async def test_claim_sql_never_takes_a_live_lease(pipe):
    """The ``UPDATE`` itself is the fence, whatever the planner thought."""
    from sm_images.pipeline.claim import claim

    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    await _claim(pipe, img)
    async with pipe.db_state.session_factory() as s:
        assert await claim(s, T, img, ["acme.x"], datetime.now(UTC), LEASE) == []
    await _expire(pipe, img, "acme.x")
    async with pipe.db_state.session_factory() as s:
        (again,) = await claim(s, T, img, ["acme.x"], datetime.now(UTC), LEASE)
        assert again.step == "acme.x"


async def test_progress_renews_the_lease_and_stops_a_lost_run(pipe):
    long = Scripted("acme.long")
    seen: list[datetime] = []

    async def works(ctx):
        await ctx.progress(50)
        async with pipe.db_state.session_factory() as s:
            from sqlalchemy import select

            row = (await s.execute(select(StepRun).where(StepRun.step == "acme.long"))).scalar_one()
            seen.append(row.lease_expires_at)
            await s.execute(  # another worker reclaims meanwhile
                update(StepRun).where(StepRun.id == row.id).values(lease_token=uuid.uuid4())
            )
            await s.commit()
        await ctx.progress(90)
        return StepOutcome.completed({"never": "recorded"})

    long.fn = works
    use_steps(long)
    coll = await pipe.collection({"acme.long": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.long"]
    assert run.status.value == "running" and run.output is None
    assert seen[0] > datetime.now(UTC) + timedelta(seconds=LEASE - 60)


async def test_concurrent_claim_runs_once(tmp_path):
    """Two real connections (a file database on SQLite): the second planner
    waits on the image lock, then finds nothing left to claim."""
    from tests.support.pg import make_db_state

    use_steps(Scripted("acme.a"), Scripted("acme.b"))
    state = await make_db_state(file=tmp_path / "race.db")
    pipe = await make_pipe(tmp_path, state)
    try:
        coll = await pipe.collection({"acme.a": {}, "acme.b": {}})
        img = await pipe.image(coll)
        now = datetime.now(UTC)
        async with state.session_factory() as first:
            claimed_1 = await plan_and_claim(first, T, img, now, LEASE)

            async def second() -> list:
                async with state.session_factory() as s:
                    found = await plan_and_claim(s, T, img, now, LEASE)
                    await s.commit()
                    return found.claims

            racer = asyncio.ensure_future(second())
            await asyncio.sleep(0.3)
            assert not racer.done()  # blocked behind the first's image lock
            await first.commit()
            claimed_2 = await asyncio.wait_for(racer, 10)
        assert sorted(c.step for c in claimed_1.claims) == ["acme.a", "acme.b"]
        assert claimed_2 == []
    finally:
        await state.engine.dispose()


async def test_lock_skips_deleted_images(pipe):
    coll = await pipe.collection({"exif": {}})
    img = await pipe.image(coll, is_deleted=True)
    await pipe.run(img)
    assert await pipe.runs(img) == {}
    async with pipe.db_state.session_factory() as s:
        assert await lock_image(s, T, img) is None


@pytest.mark.parametrize("scope", ["force"])
async def test_force_never_steals_a_live_lease(pipe, scope):
    from sm_images.pipeline.orchestrate import rerun_image

    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    await _claim(pipe, img)
    assert await rerun_image(pipe.runtime, T, img, scope) == []
    assert (await pipe.status(img), x.calls) == ({"acme.x": "running"}, 0)
