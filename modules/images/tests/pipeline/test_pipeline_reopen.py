"""Phase 3 fixes 1 and 5: a settled run only counts while it still describes
the image, and a placeholder skip reopens once its step can run.

1. A display mutator's old success must not vouch for a display copy another
   mutator wrote after it: blur, then a crop that reads the original, then
   blur re-enabled - the crop's copy is withheld and dispatch re-runs blur.
5. A ``skipped``/``not_installed`` (or ``disabled``) placeholder runs once the
   step is enabled and installed again, on dispatch and from reconcile.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sm_images.core.access import redaction
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.jobs.reconcile import reconcile_tenant
from sm_images.models import Collection, Image
from sm_images.models.enums import StepStatus
from sqlalchemy import select, update

from tests.support.pipeline import Blur, Scripted, use_steps

T = DEFAULT_TENANT


class Crop(Blur):
    """A display mutator that reads the original and redacts nothing."""

    id = "acme.crop"


async def _configure(pipe, coll, steps: dict) -> None:
    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id == coll.id)
            .values(pipeline_config={"steps": steps})
        )
        await s.commit()


async def _gate(pipe, coll_id, image_id) -> tuple[bool, bool]:
    """``(pending, trusted)`` as serving would decide them now."""
    async with pipe.db_state.session_factory() as s:
        coll = (await s.execute(select(Collection).where(Collection.id == coll_id))).scalar_one()
        img = (await s.execute(select(Image).where(Image.id == image_id))).scalar_one()
        return await redaction.pending(s, coll, img), redaction.trusts_display(coll, img)


async def test_an_old_blur_does_not_vouch_for_a_later_crop(pipe):
    blur, crop = Blur(), Crop()
    use_steps(blur, crop)
    coll = await pipe.collection({"acme.blur": {}, "renditions": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    assert (await pipe.row(img)).display_step == "acme.blur"
    assert await _gate(pipe, coll.id, img) == (False, True)

    # Switch to the crop: it reads the original and replaces the display copy.
    await _configure(
        pipe, coll, {"acme.blur": {"enabled": False}, "acme.crop": {}, "renditions": {}}
    )
    await pipe.run(img)
    assert crop.calls == 1 and (await pipe.row(img)).display_step == "acme.crop"

    # Blur back on, crop off: blur's old success says nothing about this copy.
    await _configure(
        pipe, coll, {"acme.blur": {}, "acme.crop": {"enabled": False}, "renditions": {}}
    )
    assert await _gate(pipe, coll.id, img) == (True, False)

    await pipe.run(img)  # dispatch must not think blur is settled
    assert blur.calls == 2
    row = await pipe.row(img)
    assert row.display_step == "acme.blur" and row.display_generation == 3
    assert await _gate(pipe, coll.id, img) == (False, True)
    assert (await pipe.status(img))["renditions"] == "completed"


async def test_a_reinstalled_step_runs_on_dispatch(pipe):
    x = Scripted("acme.x")
    use_steps()  # the plugin is not installed
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    run = (await pipe.runs(img))["acme.x"]
    assert (run.status, run.error_code) == (StepStatus.SKIPPED, "not_installed")

    use_steps(x)  # installed again
    await pipe.run(img)
    assert x.calls == 1 and (await pipe.status(img))["acme.x"] == "completed"


async def test_reconcile_runs_a_reinstalled_step(pipe):
    x = Scripted("acme.x")
    use_steps()
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    assert (await pipe.runs(img))["acme.x"].error_code == "not_installed"

    use_steps(x)
    done = await reconcile_tenant(pipe.runtime, T, datetime.now(UTC) + timedelta(minutes=10))
    assert done["reopened"] == 1
    assert x.calls == 1 and (await pipe.status(img))["acme.x"] == "completed"
    # Settled now: the next reconcile has nothing to reopen.
    again = await reconcile_tenant(pipe.runtime, T, datetime.now(UTC) + timedelta(minutes=20))
    assert again["reopened"] == 0 and x.calls == 1


async def _dependant_blocked(pipe, *, placeholder: bool):
    """``acme.y`` requires ``acme.x``; x is off (saved around validation), so
    y settles ``dependency_unavailable``. With ``placeholder`` x also has a
    ``disabled`` run; without, it has none."""
    from sm_images.models import StepRun

    x, y = Scripted("acme.x"), Scripted("acme.y", requires=("acme.x",))
    z = Scripted("acme.z", requires=("acme.y",))
    use_steps(x, y, z)
    coll = await pipe.collection({"acme.x": {"enabled": False}, "acme.y": {}, "acme.z": {}})
    img = await pipe.image(coll)
    if placeholder:
        async with pipe.db_state.session_factory() as s:
            s.add(StepRun(image_id=img, step="acme.x"))
            await s.commit()
    await pipe.run(img)
    runs = await pipe.runs(img)
    assert runs["acme.y"].error_code == runs["acme.z"].error_code == "dependency_unavailable"
    if placeholder:
        assert runs["acme.x"].error_code == "disabled"
    await _configure(pipe, coll, {"acme.x": {}, "acme.y": {}, "acme.z": {}})
    return img, (x, y, z)


@pytest.mark.parametrize("placeholder", [True, False])
async def test_dependants_blocked_by_a_reopened_step_run_after_it(pipe, placeholder):
    img, steps = await _dependant_blocked(pipe, placeholder=placeholder)
    await pipe.run(img)
    assert await pipe.status(img) == dict.fromkeys(["acme.x", "acme.y", "acme.z"], "completed")
    assert [s.calls for s in steps] == [1, 1, 1]


async def test_a_dependant_stays_blocked_while_its_prerequisite_is_off(pipe):
    x, y = Scripted("acme.x"), Scripted("acme.y", requires=("acme.x",))
    use_steps(x, y)
    coll = await pipe.collection({"acme.x": {"enabled": False}, "acme.y": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    await pipe.run(img)  # nothing changed: no reopen, no churn
    run = (await pipe.runs(img))["acme.y"]
    assert (run.error_code, y.calls) == ("dependency_unavailable", 0)
    assert (await pipe.row(img)).processing_generation == 1


async def test_a_placeholder_stays_while_its_step_is_still_missing_or_off(pipe):
    x = Scripted("acme.x")
    use_steps()
    coll = await pipe.collection({"acme.x": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    done = await reconcile_tenant(pipe.runtime, T, datetime.now(UTC) + timedelta(minutes=10))
    assert done["reopened"] == 0  # still not installed

    use_steps(x)
    await _configure(pipe, coll, {"acme.x": {"enabled": False}})
    await pipe.run(img)
    done = await reconcile_tenant(pipe.runtime, T, datetime.now(UTC) + timedelta(minutes=10))
    assert done["reopened"] == 0 and x.calls == 0  # installed, but switched off
