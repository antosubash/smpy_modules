"""Prompt results for someone who may only view: none for a withheld image."""

from __future__ import annotations

from sm_images.models import Image, Prompt, PromptResult
from sm_images.models.enums import StepStatus
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope
from sqlalchemy import select

from tests.collections.test_viewer_stats import _group_pending, blur_installed, seeded  # noqa: F401
from tests.support.access import OWNER, STRANGER, headers


async def test_prompt_results_of_withheld_images_are_hidden_from_a_viewer(
    client,
    seeded,  # noqa: F811
):
    group_id, pending = await _group_pending(client, seeded)
    with tenant_scope(DEFAULT_TENANT):
        async with client.db_state.session_factory() as s:
            safe = (
                await s.execute(select(Image.id).where(Image.filename == "safe.jpg"))
            ).scalar_one()
            prompt = Prompt(
                collection_id=seeded.id,
                name="count",
                instruction="Count.",
                owner_id=seeded.owner_id,
            )
            s.add(prompt)
            await s.flush()
            for image_id, group in ((safe, None), (pending, None), (None, group_id)):
                s.add(
                    PromptResult(
                        prompt_id=prompt.id,
                        image_id=image_id,
                        group_id=group,
                        status=StepStatus.COMPLETED,
                        result_data={"n": 1},
                        prompt_revision=1,
                    )
                )
            await s.commit()
            prompt_id = prompt.id
    url = f"/api/images/prompts/{prompt_id}/results"
    viewer = (await client.get(url, headers=headers(STRANGER))).json()
    assert [r["image_id"] for r in viewer["items"]] == [str(safe)]
    owner = (await client.get(url, headers=headers(OWNER))).json()
    assert {r["image_id"] for r in owner["items"]} == {str(safe), str(pending), None}
