"""Review round 1 (Codex P1/P2 and review minors) regressions."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from simple_module_db.callbacks import register_on_commit
from sm_images.contracts import DisplayWriterMissing, ImageProcessed, StepOutcome
from sm_images.models import StepRun
from sm_images.models.enums import StepStatus
from sm_images.pipeline import executor, finish
from sm_images.pipeline.config import PipelineConfigError, validate_pipeline_config
from sm_images.pipeline.executor import run_step_async
from sm_images.processing.exif import ExifData
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

from tests.pipeline.test_pipeline_leases import _claim
from tests.support.pipeline import Blur, Scripted, use_steps

T = DEFAULT_TENANT


# 1 -- two deliveries of one message never share object keys
async def test_duplicate_delivery_cannot_delete_the_winners_objects(pipe):
    blur = Blur()
    gate = asyncio.Event()
    real = blur.run

    async def first_stalls(ctx):
        if blur.calls == 0:
            blur.calls += 1
            await gate.wait()
        return await real(ctx)

    blur.run = first_stalls
    use_steps(blur)
    coll = await pipe.collection({"acme.blur": {}})
    img = await pipe.image(coll)
    token = (await _claim(pipe, img))["acme.blur"]
    loser = asyncio.ensure_future(run_step_async(pipe.runtime, T, img, "acme.blur", token))
    await asyncio.sleep(0.05)
    assert await run_step_async(pipe.runtime, T, img, "acme.blur", token) is True  # the winner
    won = await pipe.row(img)
    gate.set()
    assert await asyncio.wait_for(loser, 10) is False
    assert won.display_key in set(pipe.keys())
    assert await pipe.store.read(won.display_key)


# 2 -- a dependant of a disabled or omitted prerequisite never runs
async def test_dependant_of_a_disabled_prerequisite_is_unavailable(pipe):
    base = Scripted("acme.base")
    after = Scripted("acme.after", requires=("acme.base",))
    use_steps(base, after)
    coll = await pipe.collection({"acme.base": {"enabled": False}, "acme.after": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.after"]
    assert (run.status.value, run.error_code, after.calls) == (
        "skipped",
        "dependency_unavailable",
        0,
    )
    assert (await pipe.row(img)).processed_generation == 1


def test_strict_config_refuses_an_unmet_prerequisite(pipe):
    use_steps(Scripted("acme.base"), Scripted("acme.after", requires=("acme.base",)))
    with pytest.raises(PipelineConfigError):
        validate_pipeline_config({"steps": {"acme.after": {}}})
    validate_pipeline_config({"steps": {"acme.base": {}, "acme.after": {}}})


# 3 -- implicit rendition edges cannot form an undetected cycle
async def test_mutator_requiring_renditions_is_an_invalid_pipeline(pipe):
    blur = Blur()
    blur.requires = ("renditions",)
    use_steps(blur)
    steps = {"acme.blur": {}, "renditions": {}}
    with pytest.raises(PipelineConfigError):
        validate_pipeline_config({"steps": steps})
    coll = await pipe.collection(steps)
    img = await pipe.image(coll)
    await pipe.run(img)
    runs = await pipe.runs(img)
    assert {k: (v.status.value, v.error_code) for k, v in runs.items()} == {
        "acme.blur": ("failed", "invalid_pipeline"),
        "renditions": ("failed", "invalid_pipeline"),
    }
    assert (await pipe.row(img)).processed_generation == 1


# 5 -- the lease is checked against a clock read after the image lock
async def test_lock_wait_beyond_the_lease_rejects_the_completion(pipe, monkeypatch):
    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    token = (await _claim(pipe, img))["acme.x"]
    real_lock = finish.lock_image

    async def slow_lock(db, tenant, image_id):
        locked = await real_lock(db, tenant, image_id)
        # The lease runs out while this completion waited for the lock.
        await db.execute(
            update(StepRun)
            .where(StepRun.image_id == image_id)
            .values(lease_expires_at=datetime.now(UTC))
        )
        await asyncio.sleep(0.02)
        return locked

    monkeypatch.setattr(finish, "lock_image", slow_lock)
    assert await run_step_async(pipe.runtime, T, img, "acme.x", token) is False
    assert (await pipe.runs(img))["acme.x"].status is StepStatus.RUNNING


# 6 -- an eager drain waits for durable subscribers
class _SlowTransport:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()
        self.delivered: list = []

    async def enqueue(self, event, names, db) -> None:
        async def deliver():
            await asyncio.sleep(0.05)
            self.delivered.append(event)

        register_on_commit(db, lambda: self.tasks.add(asyncio.ensure_future(deliver())))

    async def drain(self) -> None:
        while self.tasks:
            await asyncio.gather(*list(self.tasks))
            self.tasks = {t for t in self.tasks if not t.done()}


async def test_eager_drain_waits_for_durable_deliveries(pipe):
    transport = _SlowTransport()
    pipe.bus.durable_transport = transport

    async def handler(event, ctx):  # pragma: no cover - delivered by the fake transport
        pass

    pipe.bus.subscribe_durable(ImageProcessed, handler, name="test.processed")
    coll = await pipe.collection({})
    img = await pipe.image(coll)
    await pipe.run(img)
    assert [e.image_id for e in transport.delivered] == [str(img)]


# 7 -- a plugin cannot trigger the built-in writes
async def test_plugin_staging_cannot_write_location_or_renditions(pipe):
    sneaky = Scripted("acme.sneaky")

    async def fake(ctx):
        ctx._staging.exif = ExifData(lat=10.0, lng=20.0, make="Evil")
        ctx._staging.renditions = {"small": (b"x", 1, 1)}
        return StepOutcome.completed({})

    sneaky.fn = fake
    use_steps(sneaky)
    coll = await pipe.collection({"acme.sneaky": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    row = await pipe.row(img)
    assert (row.lat, row.camera_make) == (None, None)
    assert await pipe.renditions(img) == {}
    assert pipe.keys() == [row.storage_key]


# 8 -- only a soft time limit is a time_limit failure
async def test_internal_errors_are_not_reported_as_time_limits(pipe, monkeypatch):
    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)

    async def broken(*args, **kwargs):
        raise RuntimeError("executor bug")

    monkeypatch.setattr(executor, "_work", broken)
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.x"]
    assert (run.status.value, run.error_code) == ("failed", "internal_error")


# 9 -- dead work is not re-dispatched; disabled abandoned runs settle
async def test_reconcile_skips_deleted_images(pipe):
    from sm_images.jobs.reconcile import reconcile_async

    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll, is_deleted=True)
    async with pipe.db_state.session_factory() as s:
        s.add(
            StepRun(image_id=img, step="acme.x", created_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()
    summary = await reconcile_async(pipe.runtime, datetime.now(UTC))
    assert summary.get("dispatched", 0) == 0


async def test_disabled_abandoned_running_run_is_settled(pipe):
    use_steps(Scripted("acme.x"))
    coll = await pipe.collection({"acme.x": {"enabled": False}})
    img = await pipe.image(coll)
    async with pipe.db_state.session_factory() as s:
        s.add(
            StepRun(
                image_id=img,
                step="acme.x",
                status=StepStatus.RUNNING,
                lease_token=uuid.uuid4(),
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=5),
            )
        )
        await s.commit()
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.x"]
    assert (run.status.value, run.error_code) == ("skipped", "disabled")


# 10 -- reset reports what it reset; the writer error is exported
async def test_reset_reports_only_steps_actually_reset(pipe, monkeypatch):
    from sm_images.pipeline import orchestrate
    from sm_images.pipeline.orchestrate import reset_image

    x, y = Scripted("acme.x"), Scripted("acme.y")
    x.outcome = StepOutcome.failed("boom", "x")
    use_steps(x, y)
    coll = await pipe.collection({"acme.x": {}, "acme.y": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    async with pipe.db_state.session_factory() as s:  # y is now held by a live worker
        await s.execute(
            update(StepRun)
            .where(StepRun.image_id == img, StepRun.step == "acme.y")
            .values(
                status=StepStatus.RUNNING,
                lease_token=uuid.uuid4(),
                lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await s.commit()
    # The selection saw both; the guarded UPDATE resets only the unleased one.
    monkeypatch.setattr(orchestrate, "_selected", lambda *a: ["acme.x", "acme.y"])
    async with pipe.db_state.session_factory() as s:
        assert await reset_image(s, T, img, "force") == ["acme.x"]


def test_display_writer_missing_is_a_contract():
    assert issubclass(DisplayWriterMissing, RuntimeError)
