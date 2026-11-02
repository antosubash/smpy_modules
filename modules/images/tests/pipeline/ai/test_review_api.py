"""``/api/images/.../review`` and ``/prompt-results/{id}/review`` (spec §6)."""

from __future__ import annotations

import uuid

import pytest
from sm_images.contracts.events import PromptResultReviewed
from sm_images.models import Group, Prompt, PromptResult
from sm_images.models.enums import ReviewStatus, StepStatus
from sm_images.pipeline.ai import review as review_service
from sqlalchemy import select

from tests.support.access import EDITOR, OWNER, STRANGER, VIEWER, headers
from tests.support.prompts import BASE

SCHEMA = {
    "type": "object",
    "properties": {"n": {"type": "integer"}, "kind": {"type": "string", "enum": ["a", "b"]}},
    "required": ["n"],
}


@pytest.fixture
async def queue(prompts_world):
    w = prompts_world
    async with w.c.db_state.session_factory() as s:
        prompt = Prompt(
            collection_id=uuid.UUID(w.cid), name="count", instruction="x", output_schema=SCHEMA
        )
        free = Prompt(collection_id=uuid.UUID(w.cid), name="free", instruction="y")
        s.add_all([prompt, free])
        await s.flush()
        group = Group(collection_id=uuid.UUID(w.cid), key="site-1")
        s.add(group)
        await s.flush()
        rows = [
            PromptResult(
                prompt_id=prompt.id,
                image_id=uuid.UUID(w.iid),
                status=StepStatus.COMPLETED,
                result_data={"n": 3, "kind": "a"},
                prompt_revision=1,
                model_name="m",
            ),
            PromptResult(
                prompt_id=free.id,
                group_id=group.id,
                status=StepStatus.COMPLETED,
                result_text="hello",
                prompt_revision=1,
            ),
        ]
        s.add_all(rows)
        await s.commit()
        w.rid, w.gid = rows[0].id, rows[1].id
        w.pid = str(prompt.id)
    return w


async def _items(w, who=OWNER, query=""):
    got = await w.c.get(f"{BASE}/collections/{w.cid}/review{query}", headers=headers(who))
    assert got.status_code == 200, got.text
    return got.json()["items"]


async def _review(w, rid, who=OWNER, **body):
    return await w.c.post(f"{BASE}/prompt-results/{rid}/review", json=body, headers=headers(who))


async def _row(w, rid) -> PromptResult:
    async with w.c.db_state.session_factory() as s:
        return (await s.execute(select(PromptResult).where(PromptResult.id == rid))).scalar_one()


async def test_the_queue_is_for_editors_and_hides_from_strangers(queue):
    assert [i["id"] for i in await _items(queue, EDITOR)] == [queue.rid, queue.gid]
    first = (await _items(queue))[0]
    assert (first["filename"], first["prompt_name"], first["output_visible"]) == (
        "a.jpg",
        "count",
        True,
    )
    assert first["output_schema"] == SCHEMA and first["version"]
    url = f"{BASE}/collections/{queue.cid}/review"
    assert (await queue.c.get(url, headers=headers(VIEWER))).status_code == 403
    assert (await queue.c.get(url, headers=headers(STRANGER))).status_code == 404
    only = await _items(queue, OWNER, f"?prompt={queue.pid}")
    assert [i["id"] for i in only] == [queue.rid]


async def test_review_needs_the_edit_right(queue):
    item = (await _items(queue))[0]
    body = {"action": "accept", "version": item["version"]}
    assert (await _review(queue, queue.rid, VIEWER, **body)).status_code == 403
    assert (await _review(queue, queue.rid, STRANGER, **body)).status_code == 404
    assert (await _row(queue, queue.rid)).review_status is ReviewStatus.UNREVIEWED


async def test_accept_stores_the_model_output_and_leaves_the_queue(queue):
    item = (await _items(queue))[0]
    got = await _review(queue, queue.rid, EDITOR, action="accept", version=item["version"])
    assert got.status_code == 200, got.text
    row = await _row(queue, queue.rid)
    assert row.review_status is ReviewStatus.ACCEPTED
    assert row.reviewed_data == {"n": 3, "kind": "a"} and row.reviewed_by
    assert [i["id"] for i in await _items(queue)] == [queue.gid]
    done = await _items(queue, OWNER, "?status=accepted")
    assert [i["id"] for i in done] == [queue.rid]


async def test_reject_stores_no_data(queue):
    item = (await _items(queue))[0]
    got = await _review(queue, queue.rid, action="reject", version=item["version"])
    assert got.status_code == 200
    row = await _row(queue, queue.rid)
    assert row.review_status is ReviewStatus.REJECTED and row.reviewed_data is None


async def test_correct_validates_against_the_schema(queue):
    item = (await _items(queue))[0]
    for bad in ({"n": "three"}, {"kind": "a"}, {"n": 1, "kind": "zzz"}, {"n": True}):
        got = await _review(queue, queue.rid, action="correct", data=bad, version=item["version"])
        assert (got.status_code, got.json()["code"]) == (422, "invalid_review_data"), bad
    assert (
        await _review(queue, queue.rid, action="correct", version=item["version"])
    ).status_code == 422
    assert (await _row(queue, queue.rid)).review_status is ReviewStatus.UNREVIEWED
    ok = await _review(queue, queue.rid, action="correct", data={"n": 4}, version=item["version"])
    assert ok.status_code == 200, ok.text
    row = await _row(queue, queue.rid)
    assert (row.review_status, row.reviewed_data) == (ReviewStatus.CORRECTED, {"n": 4})
    assert row.result_data == {"n": 3, "kind": "a"}  # the model's answer is kept


async def test_free_text_is_corrected_with_text(queue):
    item = next(i for i in await _items(queue) if i["id"] == queue.gid)
    assert item["group_key"] == "site-1"
    bad = await _review(queue, queue.gid, action="correct", data={"n": 1}, version=item["version"])
    assert bad.status_code == 422
    ok = await _review(
        queue, queue.gid, action="correct", data={"text": "hi"}, version=item["version"]
    )
    assert ok.status_code == 200, ok.text
    assert (await _row(queue, queue.gid)).reviewed_data == {"text": "hi"}


async def test_a_second_review_moves_the_first_into_history(queue):
    first = (await _items(queue))[0]
    await _review(queue, queue.rid, action="accept", version=first["version"])
    again = (await _items(queue, OWNER, "?status=all"))[0]
    got = await _review(queue, queue.rid, action="reject", version=again["version"])
    assert got.status_code == 200
    row = await _row(queue, queue.rid)
    assert row.review_status is ReviewStatus.REJECTED
    assert [h["review_status"] for h in row.history] == ["accepted"]


async def test_a_review_of_output_a_cannot_land_on_a_rerun_b(queue):
    item = (await _items(queue))[0]
    async with queue.c.db_state.session_factory() as s:  # the re-run completes
        row = (
            await s.execute(select(PromptResult).where(PromptResult.id == queue.rid))
        ).scalar_one()
        row.result_data = {"n": 99}
        await s.commit()
    got = await _review(queue, queue.rid, action="accept", version=item["version"])
    assert (got.status_code, got.json()["code"]) == (409, "review_stale")
    row = await _row(queue, queue.rid)
    assert row.review_status is ReviewStatus.UNREVIEWED and row.reviewed_data is None
    fresh = (await _items(queue))[0]
    assert (
        await _review(queue, queue.rid, action="accept", version=fresh["version"])
    ).status_code == 200


async def test_a_review_takes_the_image_and_group_lock(queue, monkeypatch):
    seen: list[str] = []
    real_image, real_group = review_service.lock_image, review_service.lock_group

    async def image(*a):
        seen.append("image")
        return await real_image(*a)

    async def group(*a):
        seen.append("group")
        return await real_group(*a)

    monkeypatch.setattr(review_service, "lock_image", image)
    monkeypatch.setattr(review_service, "lock_group", group)
    for rid in (queue.rid, queue.gid):
        item = next(i for i in await _items(queue) if i["id"] == rid)
        await _review(queue, rid, action="reject", version=item["version"])
    assert seen == ["image", "group"]


async def test_the_review_screen_is_an_editors(queue):
    inertia = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
    url = f"/admin/images/{queue.cid}/review"
    got = await queue.c.get(url, headers={**headers(EDITOR), **inertia})
    assert got.status_code == 200, got.text
    assert got.json()["component"] == "Images/Review"
    assert got.json()["props"]["collection"]["id"] == queue.cid
    assert (await queue.c.get(url, headers={**headers(VIEWER), **inertia})).status_code == 403
    assert (await queue.c.get(url, headers={**headers(STRANGER), **inertia})).status_code == 404


async def test_the_event_is_published_after_the_commit(queue):
    seen: list[PromptResultReviewed] = []
    queue.c.app.state.sm.event_bus.subscribe(PromptResultReviewed, seen.append)
    item = (await _items(queue))[0]
    bad = await _review(
        queue, queue.rid, action="correct", data={"n": "x"}, version=item["version"]
    )
    assert bad.status_code == 422 and seen == []  # a refused review publishes nothing
    await _review(
        queue, queue.rid, EDITOR, action="correct", data={"n": 2}, version=item["version"]
    )
    (event,) = seen
    assert (event.collection_id, event.prompt_id, event.result_id) == (
        queue.cid,
        queue.pid,
        queue.rid,
    )
    assert (event.image_id, event.group_id) == (queue.iid, None)
    assert (event.action, event.review_status, event.tenant_id) == (
        "correct",
        "corrected",
        "default",
    )
