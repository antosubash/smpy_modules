"""Task 24 fix round 1: free-text accept, refusals, size and schema failures, no N+1."""

from __future__ import annotations

import uuid

import pytest
from sm_images.ai import review as review_service
from sm_images.errors import NotFound
from sm_images.models import Collection, Group, Image, Prompt, PromptResult, Visibility
from sm_images.models.enums import StepStatus
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from tests.access_support import OWNER, collection, headers, image
from tests.prompts_support import BASE
from tests.test_review_api import _items, _review, _row, queue  # noqa: F401


async def test_accepting_free_text_keeps_the_text(queue):  # noqa: F811
    item = next(i for i in await _items(queue) if i["id"] == queue.gid)
    got = await _review(queue, queue.gid, action="accept", version=item["version"])
    assert got.status_code == 200, got.text
    assert (await _row(queue, queue.gid)).reviewed_data == {"text": "hello"}


async def test_a_trashed_images_result_cannot_be_reviewed(queue):  # noqa: F811
    item = next(i for i in await _items(queue) if i["id"] == queue.rid)
    async with queue.c.db_state.session_factory() as s:
        pic = (await s.execute(select(Image).where(Image.id == uuid.UUID(queue.iid)))).scalar_one()
        pic.is_deleted = True
        await s.commit()
    got = await _review(queue, queue.rid, action="accept", version=item["version"])
    assert got.status_code == 404, got.text


async def test_a_result_of_another_collections_prompt_is_not_found(queue):  # noqa: F811
    async with queue.c.db_state.session_factory() as s:
        other = collection("elsewhere", Visibility.PRIVATE, OWNER)
        s.add(other)
        await s.commit()
        other_id = other.id
        with pytest.raises(NotFound):
            await review_service.apply(
                s, "default", queue.rid, other_id,
                action="reject", data=None, version="x", reviewer="u", max_bytes=None,
            )  # fmt: skip


async def test_an_oversized_correction_is_422(queue):  # noqa: F811
    item = next(i for i in await _items(queue) if i["id"] == queue.rid)
    queue.c.app.state.sm_images.settings.step_output_max_bytes = 10
    got = await _review(
        queue, queue.rid, action="correct", data={"n": 1, "kind": "a"}, version=item["version"]
    )
    assert got.status_code == 422, got.text
    assert (await _row(queue, queue.rid)).reviewed_data is None


async def test_a_schema_the_builder_cannot_realise_is_invalid_schema(queue):  # noqa: F811
    broken = {"type": "object", "properties": {"x": {"$ref": "#/$defs/nope"}}}
    async with queue.c.db_state.session_factory() as s:
        prompt = (
            await s.execute(select(Prompt).where(Prompt.id == uuid.UUID(queue.pid)))
        ).scalar_one()
        prompt.output_schema = broken
        await s.commit()
    item = next(i for i in await _items(queue) if i["id"] == queue.rid)
    got = await _review(queue, queue.rid, action="correct", data={"x": 1}, version=item["version"])
    assert (got.status_code, got.json()["code"]) == (422, "invalid_schema"), got.text


async def test_the_queue_does_not_query_per_row(queue):  # noqa: F811
    async with queue.c.db_state.session_factory() as s:
        coll = (
            await s.execute(select(Collection).where(Collection.id == uuid.UUID(queue.cid)))
        ).scalar_one()
        group = (await s.execute(select(Group))).scalars().first()
        for n in range(12):
            pic = image(coll, f"x{n}.jpg")
            s.add(pic)
            await s.flush()
            s.add(
                PromptResult(
                    prompt_id=uuid.UUID(queue.pid),
                    image_id=pic.id,
                    status=StepStatus.COMPLETED,
                    result_data={"n": n},
                )
            )
        assert group is not None
        await s.commit()

    def count(url: str) -> int:
        seen: list[str] = []

        def spy(conn, cursor, statement, *a):
            seen.append(statement)

        event.listen(Engine, "before_cursor_execute", spy)
        return seen, spy  # type: ignore[return-value]

    seen, spy = count("")
    try:
        got = await queue.c.get(f"{BASE}/collections/{queue.cid}/review", headers=headers(OWNER))
    finally:
        event.remove(Engine, "before_cursor_execute", spy)
    assert got.status_code == 200 and len(got.json()["items"]) == 14
    assert len(seen) < 20, len(seen)
