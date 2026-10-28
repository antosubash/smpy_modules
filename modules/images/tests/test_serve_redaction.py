"""Review fixes 1-3 of Task 12: nothing unredacted leaks through a rendition,
an uninstalled plugin or a blocked skip.

1. A rendition is served only when it was cut from the image's current display
   generation (``Rendition.source_generation``) and no redaction is pending.
2. Protection is the persisted ``Collection.protect_originals``, not the live
   registry: uninstalling the mutator's plugin does not unprotect anything.
3. Only ``completed``, or the step's *own* skip, at the installed version,
   settles a redaction; a skip the planner decided (``dependency_*``) does not.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sm_images.models import Collection, Image, Rendition, StepRun
from sm_images.models.enums import StepStatus
from sm_images.module import ImagesModule
from sqlalchemy import select, update

from tests.access_support import EDITOR, OWNER, headers
from tests.pipeline_support import Blur, Scripted, use_steps
from tests.serve_support import seed_gallery

NO_STORE = "private, no-store"


@pytest.fixture
def blur_installed():
    use_steps(Blur())
    yield
    use_steps()


@pytest_asyncio.fixture
async def g(client, storage, blur_installed):
    ImagesModule._use_runtime(client.app, client.db_state.session_factory)
    return await seed_gallery(client.db_state.session_factory, storage)


async def _exec(client, stmt) -> None:
    async with client.db_state.session_factory() as s:
        await s.execute(stmt)
        await s.commit()


async def _configure(client, g, steps: dict, *, protect: bool | None = None) -> None:
    values: dict = {"pipeline_config": {"steps": steps}}
    if protect is not None:
        values["protect_originals"] = protect
    await _exec(
        client,
        update(Collection).where(Collection.id.in_([g.ids["pub"], g.ids["priv"]])).values(**values),
    )


async def _blur_run(client, g, status, *, code=None, version=1) -> None:
    async with client.db_state.session_factory() as s:
        for key in ("pub.plain", "priv.plain"):
            s.add(
                StepRun(
                    image_id=g.ids[key],
                    step="acme.blur",
                    status=status,
                    error_code=code,
                    step_version=version,
                )
            )
        await s.commit()


async def _flag(client, collection_id: uuid.UUID) -> bool:
    async with client.db_state.session_factory() as s:
        stmt = select(Collection.protect_originals).where(Collection.id == collection_id)
        return (await s.execute(stmt)).scalar_one()


async def _code(client, url, who=OWNER) -> int:
    return (await client.get(url, headers=headers(who))).status_code


# --- 1. stale renditions ------------------------------------------------------


async def test_rendition_publication_stamps_its_source_generation(pipe):
    use_steps(Blur())
    coll = await pipe.collection({"renditions": {}, "acme.blur": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    row = await pipe.row(img)
    rend = await pipe.renditions(img)
    assert row.display_generation == 1
    assert {r.source_generation for r in rend.values()} == {1}


async def test_a_rendition_of_an_older_display_is_404_on_both_routes(client, g):
    await _exec(
        client,
        update(Image).where(Image.id == g.ids["pub.blurred"]).values(display_generation=2),
    )
    admin = g.url("pub", "blurred", "r/small", versioned=False)
    public = g.public_url("pub", "blurred", "r/small", versioned=False)
    assert await _code(client, admin) == 404
    got = await client.get(public)
    assert got.status_code == 404
    assert got.headers["cache-control"] == "no-store"
    # Regenerated from the current display: served again.
    await _exec(
        client,
        update(Rendition)
        .where(Rendition.image_id == g.ids["pub.blurred"])
        .values(source_generation=2),
    )
    assert await _code(client, admin) == 200
    assert (await client.get(public)).status_code == 200


async def test_enabling_a_mutator_hides_existing_renditions_until_it_settles(client, g):
    await _configure(client, g, {"acme.blur": {}, "renditions": {}}, protect=True)
    for coll in ("pub", "priv"):
        assert await _code(client, g.url(coll, "plain", "r/small")) == 404
    assert (await client.get(g.public_url("pub", "plain", "r/small"))).status_code == 404
    # The blur ran and found nothing to redact: the old renditions are current.
    await _blur_run(client, g, StepStatus.COMPLETED)
    assert await _code(client, g.url("priv", "plain", "r/small")) == 200
    assert (await client.get(g.public_url("pub", "plain", "r/small"))).status_code == 200


# --- 2. protection is persisted -----------------------------------------------


async def put(client, g, steps):
    url = f"/api/images/collections/{g.ids['priv']}/pipeline"
    return await client.put(url, json={"steps": steps}, headers=headers(OWNER))


async def test_saving_a_mutator_sets_protect_originals(client, g):
    assert await _flag(client, g.ids["priv"]) is False
    assert (await put(client, g, {"acme.blur": {}})).status_code == 200
    assert await _flag(client, g.ids["priv"]) is True


async def test_uninstalling_the_mutator_keeps_originals_protected(client, g):
    assert (await put(client, g, {"acme.blur": {}})).status_code == 200
    await _blur_run(client, g, StepStatus.COMPLETED)
    assert await _code(client, g.url("priv", "plain", "display")) == 200
    use_steps()  # the plugin is gone
    assert await _code(client, g.url("priv", "plain", "display")) == 404
    assert await _code(client, g.url("priv", "plain", "r/small")) == 404
    assert await _code(client, g.url("priv", "plain", "original"), EDITOR) == 403
    owner = await client.get(g.url("priv", "plain", "original"), headers=headers(OWNER))
    assert (owner.status_code, owner.headers["cache-control"]) == (200, NO_STORE)
    # A save that still names the missing step cannot clear the flag...
    assert (await put(client, g, {"acme.blur": {}, "exif": {}})).status_code == 200
    assert await _flag(client, g.ids["priv"]) is True
    # ...an owner's save with no mutator and every step installed does.
    assert (await put(client, g, {"exif": {}})).status_code == 200
    assert await _flag(client, g.ids["priv"]) is False
    assert await _code(client, g.url("priv", "plain", "display")) == 200


async def test_a_step_that_no_longer_mutates_does_not_unprotect(client, g):
    await _configure(client, g, {"acme.blur": {}}, protect=True)
    tame = Scripted("acme.blur")  # same id, now registered without mutates_display
    use_steps(tame)
    await _blur_run(client, g, StepStatus.COMPLETED)
    assert await _code(client, g.url("priv", "plain", "display")) == 404
    assert await _code(client, g.url("priv", "plain", "original"), EDITOR) == 403


async def test_an_enabled_step_that_is_not_installed_fails_closed(client, g):
    await _configure(client, g, {"acme.unknown": {}})
    assert await _code(client, g.url("priv", "plain", "display")) == 404
    assert await _code(client, g.url("priv", "plain", "r/small")) == 404
    assert await _code(client, g.url("priv", "plain", "original"), EDITOR) == 403


# --- 3. what settles a redaction ----------------------------------------------


@pytest.mark.parametrize(
    "code", ["dependency_unavailable", "dependency_stale", "dependency_failed", "not_installed"]
)
async def test_a_blocked_skip_does_not_settle(client, g, code):
    await _configure(client, g, {"acme.blur": {}}, protect=True)
    await _blur_run(client, g, StepStatus.SKIPPED, code=code)
    assert await _code(client, g.url("priv", "plain", "display")) == 404
    assert await _code(client, g.url("priv", "plain", "original"), EDITOR) == 403


async def test_the_steps_own_skip_settles(client, g):
    await _configure(client, g, {"acme.blur": {}}, protect=True)
    await _blur_run(client, g, StepStatus.SKIPPED, code=None)
    assert await _code(client, g.url("priv", "plain", "display"), EDITOR) == 200


async def test_a_result_of_an_older_step_version_does_not_settle(client, g):
    await _configure(client, g, {"acme.blur": {}}, protect=True)
    await _blur_run(client, g, StepStatus.COMPLETED, version=0)
    assert await _code(client, g.url("priv", "plain", "display")) == 404


# --- round 2: an existing display copy is already redacted ----------------------


async def test_a_rerunning_mutator_still_serves_the_existing_display(client, g):
    await _configure(client, g, {"acme.blur": {}, "renditions": {}}, protect=True)
    async with client.db_state.session_factory() as s:
        for key in ("pub.blurred", "priv.blurred"):
            s.add(
                StepRun(
                    image_id=g.ids[key], step="acme.blur", status=StepStatus.PENDING, step_version=1
                )
            )
        await s.commit()
    display = await client.get(g.url("priv", "blurred", "display"), headers=headers(EDITOR))
    assert (display.status_code, display.content) == (200, g.bytes["priv.blurred.display"])
    small = await client.get(g.url("priv", "blurred", "r/small"), headers=headers(EDITOR))
    assert (small.status_code, small.content) == (200, g.bytes["priv.blurred.small"])
    assert (await client.get(g.public_url("pub", "blurred", "r/small"))).status_code == 200
    # The original stays protected all the same.
    assert await _code(client, g.url("priv", "blurred", "original"), EDITOR) == 403


async def test_an_uninstalled_plugin_withholds_its_displays_too(client, g):
    """Fix round 4 reverses round 2: a step that is not installed cannot vouch
    for its copy (it may have been a crop), so every display waits."""
    await _configure(client, g, {"acme.blur": {}}, protect=True)
    use_steps()  # the plugin is gone
    for name in ("blurred", "plain"):
        for tail in ("display", "r/small"):
            assert await _code(client, g.url("priv", name, tail), EDITOR) == 404
            assert (await client.get(g.public_url("pub", name, tail))).status_code == 404
        assert await _code(client, g.url("priv", name, "original"), EDITOR) == 403
