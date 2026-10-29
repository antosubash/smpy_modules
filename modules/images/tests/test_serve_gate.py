"""The original is not "the display" while a display mutator has not settled.

With no display copy the original is what everyone sees, unless the
collection enables a step that writes one (a blur) and that step has not
finished for this image: until then the original is the unblurred picture, so
``…/display`` withholds it (404, the portal's "thumbnail not available") and
``…/original`` treats it as protected (``can_view_original``, ``no-store``).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_images.models import StepRun
from sm_images.models.enums import StepStatus

from tests.access_support import EDITOR, OWNER, headers
from tests.pipeline_support import Blur, use_steps
from tests.serve_support import seed_gallery

NO_STORE = "private, no-store"
PRIVATE = "private, max-age=3600"


@pytest.fixture
def blur_installed():
    use_steps(Blur())
    yield
    use_steps()


@pytest_asyncio.fixture
async def g(client, storage, blur_installed):
    return await seed_gallery(
        client.db_state.session_factory,
        storage,
        pipeline_config={"steps": {"acme.blur": {}}},
    )


async def _run(client, g, status: StepStatus | None) -> None:
    if status is None:
        return
    async with client.db_state.session_factory() as s:
        for key in ("pub.plain", "priv.plain"):
            s.add(StepRun(image_id=g.ids[key], step="acme.blur", status=status, step_version=1))
        await s.commit()


@pytest.mark.parametrize(
    "status", [None, StepStatus.PENDING, StepStatus.RUNNING, StepStatus.FAILED]
)
async def test_unsettled_mutator_withholds_the_original(client, g, status):
    await _run(client, g, status)
    display = await client.get(g.url("priv", "plain", "display"), headers=headers(OWNER))
    assert display.status_code == 404
    assert g.bytes["priv.plain.original"] not in display.content
    shared = await client.get(g.url("priv", "plain", "original"), headers=headers(EDITOR))
    assert shared.status_code == 403
    owner = await client.get(g.url("priv", "plain", "original"), headers=headers(OWNER))
    assert (owner.status_code, owner.headers["cache-control"]) == (200, NO_STORE)
    public = await client.get(g.public_url("pub", "plain", "display"))
    assert public.status_code == 404
    assert (await client.get(g.public_url("pub", "plain", "original"))).status_code == 404


@pytest.mark.parametrize("status", [StepStatus.COMPLETED, StepStatus.SKIPPED])
async def test_settled_mutator_that_wrote_nothing_serves_the_original(client, g, status):
    await _run(client, g, status)
    display = await client.get(g.url("priv", "plain", "display"), headers=headers(EDITOR))
    assert display.status_code == 200
    assert display.content == g.bytes["priv.plain.original"]
    original = await client.get(g.url("priv", "plain", "original"), headers=headers(EDITOR))
    assert (original.status_code, original.headers["cache-control"]) == (200, PRIVATE)


async def test_a_disabled_mutator_does_not_gate(client, storage, blur_installed):
    g = await seed_gallery(
        client.db_state.session_factory,
        storage,
        pipeline_config={"steps": {"acme.blur": {"enabled": False}}},
    )
    got = await client.get(g.url("priv", "plain", "display"), headers=headers(EDITOR))
    assert got.status_code == 200
