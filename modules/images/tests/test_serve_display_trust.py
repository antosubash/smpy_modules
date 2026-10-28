"""Review fix 4 of Task 12: when a display copy counts as redacted.

``redaction.trusts_display`` trusts a display copy only when the step that
wrote it is enabled, installed and a display mutator, *and* no other enabled
step is a display mutator or uninstalled (an unknown step might be one).
``prompt:*`` steps never write a display copy and are left out. A version bump
of the writing step still counts. Anything else is withheld with its
renditions while redaction is pending, and the original stays protected.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sm_images.models import Collection, Image, StepRun
from sm_images.models.enums import StepStatus
from sqlalchemy import update

from tests.access_support import EDITOR, OWNER, headers
from tests.pipeline_support import Blur, use_steps
from tests.serve_support import seed_gallery

TAILS = ("display", "r/small")


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


def _ids(g) -> list:
    return [g.ids["pub.blurred"], g.ids["priv.blurred"]]


async def _set(client, g, steps: dict, **image_values) -> None:
    async with client.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id.in_([g.ids["pub"], g.ids["priv"]]))
            .values(pipeline_config={"steps": steps}, protect_originals=True)
        )
        if image_values:
            await s.execute(update(Image).where(Image.id.in_(_ids(g))).values(**image_values))
        await s.commit()


async def _blur_completed(client, g) -> None:
    async with client.db_state.session_factory() as s:
        for image_id in _ids(g):
            s.add(
                StepRun(
                    image_id=image_id, step="acme.blur", status=StepStatus.COMPLETED, step_version=1
                )
            )
        await s.commit()


async def _codes(client, g) -> set[int]:
    out = set()
    for tail in TAILS:
        got = await client.get(g.url("priv", "blurred", tail), headers=headers(EDITOR))
        out.add(got.status_code)
        out.add((await client.get(g.public_url("pub", "blurred", tail))).status_code)
    return out


async def _original_protected(client, g) -> None:
    url = g.url("priv", "blurred", "original")
    assert (await client.get(url, headers=headers(EDITOR))).status_code == 403
    owner = await client.get(url, headers=headers(OWNER))
    assert (owner.status_code, owner.headers["cache-control"]) == (200, "private, no-store")


async def test_an_uninstalled_crops_display_waits_for_a_newly_enabled_blur(client, g):
    """Codex's reproduction: the crop that wrote the display is uninstalled but
    still enabled, and an anonymiser has since been enabled beside it."""
    use_steps(Blur())  # acme.crop is gone
    await _set(client, g, {"acme.crop": {}, "acme.blur": {}}, display_step="acme.crop")
    assert await _codes(client, g) == {404}
    await _original_protected(client, g)
    # The blur completes and rewrites the display copy...
    await _blur_completed(client, g)
    await _set(client, g, {"acme.crop": {}, "acme.blur": {}}, display_step="acme.blur")
    # ...but the unknown crop is still enabled and might mutate again: fail closed.
    assert await _codes(client, g) == {404}
    await _original_protected(client, g)
    # The owner drops the missing step: the blur's copy is served.
    await _set(client, g, {"acme.blur": {}})
    assert await _codes(client, g) == {200}


async def test_two_enabled_installed_mutators_trust_neither(client, g):
    # Saved around validation (strict refuses two mutators).
    await _set(client, g, {"acme.blur": {}, "acme.crop": {}}, display_step="acme.blur")
    assert await _codes(client, g) == {404}
    await _original_protected(client, g)


async def test_another_enabled_uninstalled_step_withdraws_trust(client, g):
    await _set(client, g, {"acme.blur": {}, "acme.gone": {}}, display_step="acme.blur")
    assert await _codes(client, g) == {404}
    await _original_protected(client, g)


async def test_prompt_steps_do_not_withdraw_trust(client, g):
    await _set(client, g, {"acme.blur": {}, "prompt:caption": {}}, display_step="acme.blur")
    assert await _codes(client, g) == {200}


async def test_a_version_bump_of_the_writing_step_is_still_trusted(client, g):
    await _set(client, g, {"acme.blur": {}}, display_step="acme.blur", display_step_version=0)
    async with client.db_state.session_factory() as s:
        for image_id in _ids(g):
            s.add(
                StepRun(
                    image_id=image_id, step="acme.blur", status=StepStatus.PENDING, step_version=0
                )
            )
        await s.commit()
    assert await _codes(client, g) == {200}
