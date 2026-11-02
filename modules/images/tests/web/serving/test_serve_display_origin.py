"""Review fix 3.1 of Task 12: a display copy is redacted only by the mutator
the collection runs *now*.

Any ``mutates_display`` step writes a display copy - a crop as well as an
anonymiser. ``Image.display_step``/``display_step_version`` record which step
wrote it, at the fenced publication; serving trusts the copy without asking
the redaction gate only when that step is the collection's enabled display
mutator (a version bump of the same step still counts). Otherwise the copy is
treated like the original: withheld, with its renditions, until the current
mutator settles.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sqlalchemy import update

from tests.support.access import EDITOR, OWNER, headers
from tests.support.pipeline import Blur, use_steps
from tests.support.serve import seed_gallery


class Crop(Blur):
    """A display mutator that redacts nothing."""

    id = "acme.crop"


@pytest.fixture
def both_installed():
    use_steps(Blur(), Crop())
    yield
    use_steps()


@pytest_asyncio.fixture
async def g(client, storage, both_installed):
    return await seed_gallery(client.db_state.session_factory, storage)


async def _exec(client, *stmts) -> None:
    async with client.db_state.session_factory() as s:
        for stmt in stmts:
            await s.execute(stmt)
        await s.commit()


async def _code(client, url, who=EDITOR) -> int:
    return (await client.get(url, headers=headers(who))).status_code


def _configure(g, steps: dict) -> object:
    return (
        update(Collection)
        .where(Collection.id.in_([g.ids["pub"], g.ids["priv"]]))
        .values(pipeline_config={"steps": steps}, protect_originals=True)
    )


async def test_publication_records_the_step_that_wrote_the_display(pipe):
    use_steps(Crop())
    coll = await pipe.collection({"acme.crop": {}, "renditions": {}})
    img = await pipe.image(coll)
    await pipe.run(img)
    row = await pipe.row(img)
    assert row.display_key is not None
    assert (row.display_step, row.display_step_version) == ("acme.crop", Crop.version)


async def test_a_display_from_another_mutator_is_withheld_until_the_current_one_settles(client, g):
    ids = [g.ids["pub.blurred"], g.ids["priv.blurred"]]
    await _exec(
        client,
        update(Image).where(Image.id.in_(ids)).values(display_step="acme.crop"),
        _configure(g, {"acme.blur": {}}),
    )
    for tail in ("display", "r/small"):
        assert await _code(client, g.url("priv", "blurred", tail)) == 404
        assert (await client.get(g.public_url("pub", "blurred", tail))).status_code == 404
    assert await _code(client, g.url("priv", "blurred", "original")) == 403
    owner = await client.get(g.url("priv", "blurred", "original"), headers=headers(OWNER))
    assert owner.headers["cache-control"] == "private, no-store"
    # The anonymiser has run over it (and found nothing more to blur).
    async with client.db_state.session_factory() as s:
        for image_id in ids:
            s.add(
                StepRun(
                    image_id=image_id, step="acme.blur", status=StepStatus.COMPLETED, step_version=1
                )
            )
        await s.commit()
    for tail in ("display", "r/small"):
        assert await _code(client, g.url("priv", "blurred", tail)) == 200
        assert (await client.get(g.public_url("pub", "blurred", tail))).status_code == 200


async def test_a_version_bump_of_the_same_mutator_keeps_serving(client, g):
    ids = [g.ids["pub.blurred"], g.ids["priv.blurred"]]
    await _exec(
        client,
        # written by an older acme.blur, which is re-running now
        update(Image).where(Image.id.in_(ids)).values(display_step_version=0),
        _configure(g, {"acme.blur": {}}),
    )
    async with client.db_state.session_factory() as s:
        for image_id in ids:
            s.add(
                StepRun(
                    image_id=image_id, step="acme.blur", status=StepStatus.PENDING, step_version=0
                )
            )
        await s.commit()
    for tail in ("display", "r/small"):
        assert await _code(client, g.url("priv", "blurred", tail)) == 200
        assert (await client.get(g.public_url("pub", "blurred", tail))).status_code == 200


async def test_a_display_with_no_recorded_step_is_not_trusted(client, g):
    await _exec(
        client,
        update(Image).where(Image.id == g.ids["priv.blurred"]).values(display_step=None),
        _configure(g, {"acme.blur": {}}),
    )
    assert await _code(client, g.url("priv", "blurred", "display")) == 404
    assert await _code(client, g.url("priv", "blurred", "r/small")) == 404
