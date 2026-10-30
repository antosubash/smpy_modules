"""A prompt step's run carries the prompt's answer in the viewer (QA retest 2).

The viewer showed only ``model`` and ``structured: true``; the answer was on
the Review screen alone. ``answer`` holds the result's data (the reviewed
correction when there is one) or text. An editor always gets it; a viewer only
for an image whose picture may be shown - the gate the results list applies.
"""

from __future__ import annotations

import uuid

from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.models import Collection, Image, Prompt, PromptResult, StepRun, StepStatus
from sm_images.web.services.prompt_answers import answers
from sqlalchemy import update

from tests.support.stub_auth import as_user
from tests.support.upload import WRITER, jpeg, make_collection, post_files

PUBLISHER = as_user("olga", (*WRITER, "images.publish"))
VIEWER = as_user("sam", ("images.view",))


async def _seed(client, *, data=None, text=None, reviewed=None) -> tuple[str, str]:
    cid = await make_collection(client, PUBLISHER, visibility="internal")
    got = await post_files(client, cid, [("a.jpg", jpeg(), "image/jpeg")], headers=PUBLISHER)
    iid = got.json()["results"][0]["id"]
    pid = uuid.uuid4()
    async with client.db_state.session_factory() as s:
        s.add(
            Prompt(
                id=pid,
                tenant_id=DEFAULT_TENANT,
                collection_id=uuid.UUID(cid),
                name="Land cover",
                instruction="?",
            )
        )
        await s.flush()
        s.add(StepRun(image_id=uuid.UUID(iid), step=f"prompt:{pid}", status=StepStatus.COMPLETED))
        s.add(
            PromptResult(
                tenant_id=DEFAULT_TENANT,
                prompt_id=pid,
                image_id=uuid.UUID(iid),
                status=StepStatus.COMPLETED,
                result_data=data,
                result_text=text,
                reviewed_data=reviewed,
            )
        )
        await s.commit()
    return cid, iid


def _answer(body: dict) -> dict | None:
    (run,) = [r for r in body["step_runs"] if r["step"].startswith("prompt:")]
    return run["answer"]


async def test_an_editor_sees_the_structured_answer(uploads):
    _, iid = await _seed(uploads, data={"land_cover": "forest", "confidence": 0.95})
    body = (await uploads.get(f"/api/images/images/{iid}", headers=PUBLISHER)).json()
    assert _answer(body) == {"data": {"land_cover": "forest", "confidence": 0.95}, "text": None}


async def test_a_correction_wins_and_free_text_is_kept(uploads):
    _, iid = await _seed(uploads, data={"n": 1}, text="one tree", reviewed={"n": 2})
    body = (await uploads.get(f"/api/images/images/{iid}", headers=PUBLISHER)).json()
    assert _answer(body) == {"data": {"n": 2}, "text": "one tree"}


async def test_a_viewer_sees_it_only_once_the_picture_may_be_shown(uploads):
    cid, iid = await _seed(uploads, text="a street")
    url = f"/api/images/images/{iid}"
    assert _answer((await uploads.get(url, headers=VIEWER)).json()) == {
        "data": None,
        "text": "a street",
    }
    async with uploads.db_state.session_factory() as s:  # the original is protected now
        await s.execute(
            update(Collection).where(Collection.id == uuid.UUID(cid)).values(protect_originals=True)
        )
        await s.commit()
    # A withheld image is not the viewer's to open at all; the answer gate
    # below it says the same on its own (defence in depth).
    assert (await uploads.get(url, headers=VIEWER)).status_code == 404
    assert _answer((await uploads.get(url, headers=PUBLISHER)).json()) is not None
    async with uploads.db_state.session_factory() as s:
        coll = await s.get(Collection, uuid.UUID(cid))
        image = await s.get(Image, uuid.UUID(iid))
        assert await answers(s, coll, image, editor=False) == {}
        assert await answers(s, coll, image, editor=True) != {}
