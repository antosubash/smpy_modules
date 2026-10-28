"""The executor's status rules, built-in writes and ordering (eager drain)."""

from __future__ import annotations

from datetime import UTC, datetime

from sm_images.contracts import ImageProcessed, StepOutcome
from sm_images.models import Collection, LocationSource
from sm_images.pipeline import registry
from sm_images.pipeline.orchestrate import rerun_image
from sm_images.pipeline.plan import is_stale
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import select, update

from tests.pipeline_support import FIX, Blur, Scripted, use_steps

T = DEFAULT_TENANT


async def test_skipped_is_final_for_version(pipe):
    maybe = Scripted("acme.maybe")
    maybe.outcome = StepOutcome.skipped("no faces")
    use_steps(maybe)
    coll = await pipe.collection({"acme.maybe": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.maybe"]
    assert (run.status.value, run.output, run.error_code) == (
        "skipped",
        {"reason": "no faces"},
        None,
    )
    await pipe.run(img)
    assert await rerun_image(pipe.runtime, T, img, "retry") == []
    assert maybe.calls == 1
    assert await rerun_image(pipe.runtime, T, img, "force") == ["acme.maybe"]
    assert maybe.calls == 2


async def test_exif_writes_location_camera_and_zone_aware_time(pipe):
    coll = await pipe.collection({"exif": {}})
    img = await pipe.image(coll, (FIX / "geotagged.jpg").read_bytes())
    await pipe.run(img)
    assert (await pipe.status(img)) == {"exif": "completed"}
    row = await pipe.row(img)
    assert (round(row.lat, 3), round(row.lng, 3)) == (-33.865, -151.21)
    assert row.location_source == LocationSource.EXIF
    assert (row.camera_make, row.camera_model) == ("Acme", "Cam-1")
    assert row.captured_at == datetime(2024, 3, 5, 12, 30, 15, tzinfo=UTC)
    async with pipe.db_state.session_factory() as s:
        c = (await s.execute(select(Collection).where(Collection.id == coll.id))).scalar_one()
    assert c.located_count == 1 and round(c.bbox_minx, 2) == -151.21


async def test_exif_never_overrides_manual_location(pipe):
    coll = await pipe.collection({"exif": {}})
    data = (FIX / "geotagged.jpg").read_bytes()
    img = await pipe.image(coll, data, lat=1.0, lng=2.0, location_source=LocationSource.MANUAL)
    await pipe.run(img)
    row = await pipe.row(img)
    assert (row.lat, row.lng, row.location_source) == (1.0, 2.0, LocationSource.MANUAL)
    assert row.camera_make == "Acme"
    assert (await pipe.runs(img))["exif"].output["lat"] is not None


async def test_manual_edit_between_load_and_store_wins(pipe, monkeypatch):
    coll = await pipe.collection({"exif": {}})
    img = await pipe.image(coll, (FIX / "geotagged.jpg").read_bytes())
    step = registry.get_step("exif")
    real = step.run

    async def edited_meanwhile(ctx):
        outcome = await real(ctx)
        async with pipe.db_state.session_factory() as s:  # a manual edit commits first
            from sm_images.models import Image

            await s.execute(
                update(Image)
                .where(Image.id == img)
                .values(lat=5.0, lng=6.0, location_source=LocationSource.MANUAL)
            )
            await s.commit()
        return outcome

    monkeypatch.setattr(step, "run", edited_meanwhile)
    await pipe.run(img)
    row = await pipe.row(img)
    assert (row.lat, row.lng, row.location_source) == (5.0, 6.0, LocationSource.MANUAL)
    assert (await pipe.status(img)) == {"exif": "completed"}


async def test_failed_step_does_not_block_independent(pipe):
    bad = Scripted("acme.bad")
    bad.outcome = StepOutcome.failed("boom", "it broke")
    after = Scripted("acme.after", requires=("acme.bad",))
    use_steps(bad, after)
    coll = await pipe.collection({"acme.bad": {}, "acme.after": {}, "exif": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    runs = await pipe.runs(img)
    assert {k: v.status.value for k, v in runs.items()} == {
        "acme.bad": "failed",
        "acme.after": "skipped",
        "exif": "completed",
    }
    assert runs["acme.bad"].error_code == "boom"
    assert runs["acme.after"].error_code == "dependency_failed"
    assert after.calls == 0
    row = await pipe.row(img)
    assert row.processed_generation == row.processing_generation == 1

    bad.outcome = StepOutcome.completed({})
    assert sorted(await rerun_image(pipe.runtime, T, img, "retry")) == ["acme.after", "acme.bad"]
    assert await pipe.status(img) == {
        "acme.bad": "completed",
        "acme.after": "completed",
        "exif": "completed",
    }
    assert after.calls == 1


async def test_dependants_dispatch_after_completion(pipe):
    blur = Blur()
    use_steps(blur)
    coll = await pipe.collection({"renditions": {}, "acme.blur": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    runs = await pipe.runs(img)
    assert {k: v.status.value for k, v in runs.items()} == {
        "acme.blur": "completed",
        "renditions": "completed",
    }
    assert runs["acme.blur"].finished_at <= runs["renditions"].started_at
    row = await pipe.row(img)
    assert row.display_generation == 1 and row.display_key.endswith(".jpg")
    assert row.storage_key != row.display_key
    rend = await pipe.renditions(img)
    # Cut from the 32x24 display copy, not the 64x48 original.
    assert {s: (r.width, r.height) for s, r in rend.items()} == {
        "small": (16, 12),
        "medium": (32, 24),
    }
    assert set(pipe.keys()) == {
        row.storage_key,
        row.display_key,
        *(r.storage_key for r in rend.values()),
    }


async def test_not_installed_and_disabled_steps_settle(pipe):
    coll = await pipe.collection({"gone.step": {}, "exif": {"enabled": False}, "renditions": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    runs = await pipe.runs(img)
    assert (runs["gone.step"].status.value, runs["gone.step"].error_code) == (
        "skipped",
        "not_installed",
    )
    assert "exif" not in runs
    assert runs["renditions"].status.value == "completed"
    assert (await pipe.row(img)).processed_generation == 1


async def test_force_reruns_all(pipe):
    seen: list[ImageProcessed] = []

    async def on(event):
        seen.append(event)

    pipe.bus.subscribe(ImageProcessed, on)
    x = Scripted("acme.x")
    use_steps(x)
    coll = await pipe.collection({"exif": {}, "renditions": {}, "acme.x": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    await pipe.run(img)  # a repeated dispatch decides nothing new
    assert [e.processing_generation for e in seen] == [1]
    assert sorted(await rerun_image(pipe.runtime, T, img, "force")) == [
        "acme.x",
        "exif",
        "renditions",
    ]
    runs = await pipe.runs(img)
    assert {r.attempts for r in runs.values()} == {2}
    assert {r.status.value for r in runs.values()} == {"completed"}
    assert x.calls == 2
    assert [e.processing_generation for e in seen] == [1, 2]
    assert seen[0].image_id == str(img) and seen[0].tenant_id == T


async def test_version_bump_marks_stale(pipe):
    v1 = Scripted("acme.v")
    use_steps(v1)
    coll = await pipe.collection({"acme.v": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    assert (await pipe.runs(img))["acme.v"].step_version == 1

    v2 = Scripted("acme.v", version=2)
    use_steps(v2)
    from sm_images.pipeline.advance import view

    run = (await pipe.runs(img))["acme.v"]
    assert is_stale(view(run, datetime.now(UTC)))
    await pipe.run(img)
    assert await rerun_image(pipe.runtime, T, img, "retry") == []
    assert v2.calls == 0  # a version bump alone never re-runs a final result
    assert await rerun_image(pipe.runtime, T, img, "stale") == ["acme.v"]
    run = (await pipe.runs(img))["acme.v"]
    assert (v2.calls, run.step_version, run.status.value) == (1, 2, "completed")
    assert not is_stale(view(run, datetime.now(UTC)))


async def test_output_cap(pipe, tmp_path):
    from tests.pipeline_support import make_pipe

    small = await make_pipe(tmp_path / "s", pipe.db_state, step_output_max_bytes=64)
    big = Scripted("acme.big")
    big.outcome = StepOutcome.completed({"blob": "x" * 200})
    nan = Scripted("acme.nan")
    nan.outcome = StepOutcome.completed({"v": float("nan")})
    fits = Scripted("acme.fits")
    use_steps(big, nan, fits)
    coll = await small.collection({"acme.big": {}, "acme.nan": {}, "acme.fits": {}})
    img = await small.image(coll)
    await small.run(img)
    runs = await small.runs(img)
    assert (runs["acme.big"].status.value, runs["acme.big"].error_code) == (
        "failed",
        "output_too_large",
    )
    assert runs["acme.big"].output is None
    assert (runs["acme.nan"].status.value, runs["acme.nan"].error_code) == (
        "failed",
        "invalid_output",
    )
    assert (runs["acme.fits"].status.value, runs["acme.fits"].output) == ("completed", {"ok": True})


async def test_step_exception_is_a_bounded_failure(pipe):
    boom = Scripted("acme.boom")

    async def explode(ctx):
        raise ValueError("x" * 5000)

    boom.fn = explode
    use_steps(boom)
    coll = await pipe.collection({"acme.boom": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.boom"]
    assert (run.status.value, run.error_code) == ("failed", "step_error")
    assert len(run.error_message) == 2000 and run.lease_token is None
