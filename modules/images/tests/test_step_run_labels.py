"""A prompt step's run is labelled with the prompt's name in the viewer (QA TEST-014).

The viewer listed it as ``prompt:<uuid>``. The detail response now carries a
``label``: the prompt's name, ``None`` for a built-in step (the client names
those) and for a prompt that was deleted (the id stays the fallback).
"""

from __future__ import annotations

import uuid

from sm_images.models import Collection, Prompt, StepRun, StepStatus
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

from tests.upload_support import OLGA, jpeg, make_collection, post_files


async def test_prompt_runs_carry_the_prompt_name(uploads):
    cid = await make_collection(uploads, OLGA)
    got = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")])
    iid = uuid.UUID(got.json()["results"][0]["id"])
    kept, gone = uuid.uuid4(), uuid.uuid4()
    async with uploads.db_state.session_factory() as s:
        s.add(
            Prompt(
                id=kept,
                tenant_id=DEFAULT_TENANT,
                collection_id=uuid.UUID(cid),
                name="Land cover",
                instruction="What land cover?",
            )
        )
        for pid in (kept, gone):
            s.add(StepRun(image_id=iid, step=f"prompt:{pid}", status=StepStatus.COMPLETED))
        await s.commit()

    body = (await uploads.get(f"/api/images/images/{iid}", headers=OLGA)).json()
    labels = {r["step"]: r["label"] for r in body["step_runs"]}
    assert labels[f"prompt:{kept}"] == "Land cover"
    assert labels[f"prompt:{gone}"] is None
    assert all(label is None for step, label in labels.items() if not step.startswith("prompt:"))


async def test_the_pipeline_overview_names_prompt_steps(uploads):
    """Review follow-up: the Pipeline tab listed a prompt step as ``prompt:<uuid>``."""
    cid = await make_collection(uploads, OLGA)
    pid = uuid.uuid4()
    async with uploads.db_state.session_factory() as s:
        s.add(
            Prompt(
                id=pid,
                tenant_id=DEFAULT_TENANT,
                collection_id=uuid.UUID(cid),
                name="Land cover",
                instruction="What land cover?",
            )
        )
        await s.commit()
    body = (await uploads.get(f"/api/images/collections/{cid}/pipeline", headers=OLGA)).json()
    labels = {s["id"]: s.get("label") for s in body["steps"]}
    assert labels[f"prompt:{pid}"] == "Land cover"
    assert labels["exif"] is None


async def test_an_enabled_prompt_step_is_listed_once(uploads):
    """QA round 2: enabling a prompt step listed it twice (it is in both the
    configured steps and the prompt steps), with a duplicate React key."""
    cid = await make_collection(uploads, OLGA)
    pid = uuid.uuid4()
    async with uploads.db_state.session_factory() as s:
        s.add(
            Prompt(
                id=pid,
                tenant_id=DEFAULT_TENANT,
                collection_id=uuid.UUID(cid),
                name="Land cover",
                instruction="What land cover?",
            )
        )
        await s.execute(
            update(Collection)
            .where(Collection.id == uuid.UUID(cid))
            .values(pipeline_config={"steps": {f"prompt:{pid}": {"enabled": True}}})
        )
        await s.commit()
    body = (await uploads.get(f"/api/images/collections/{cid}/pipeline", headers=OLGA)).json()
    ids = [s["id"] for s in body["steps"]]
    assert ids.count(f"prompt:{pid}") == 1
    assert len(ids) == len(set(ids))
