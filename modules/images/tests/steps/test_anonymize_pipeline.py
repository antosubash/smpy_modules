"""``anonymize`` under the executor: a display copy beside an untouched original,
renditions cut from it, and the original behind its own right (spec §2, §3)."""

from __future__ import annotations

import uuid

from PIL import ImageChops, ImageStat
from sm_images.models import Collection, Visibility
from sm_images.steps.anonymize import Detection
from sqlalchemy import update

from tests.support.access import EDITOR, MANAGER, OWNER, VIEWER, collection, headers, share
from tests.support.anonymize import FakeDetector, decode, picture, use_anonymize
from tests.support.pipeline import make_pipe
from tests.support.stub_auth import as_user

FACE = Detection("face", 24, 18, 16, 12, 0.9)
ORIGINALS = as_user("orla", ("images.view", "images.originals.view"))
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


def _distance(a: bytes, b: bytes) -> float:
    left, right = decode(a), decode(b)
    if left.size != right.size:
        right = right.resize(left.size)
    return sum(ImageStat.Stat(ImageChops.difference(left, right)).mean)


async def test_display_written_original_untouched(pipe):
    use_anonymize(FakeDetector([FACE]))
    coll = await pipe.collection({"anonymize": {}, "renditions": {}})
    data = picture()
    img = await pipe.image(coll, data)
    key = (await pipe.row(img)).storage_key
    await pipe.run(img)
    row = await pipe.row(img)
    assert (await pipe.status(img))["anonymize"] == "completed"
    assert row.storage_key == key
    assert await pipe.store.read(key) == data  # byte for byte
    assert row.display_key is not None and row.display_key != key
    assert (row.display_step, row.display_generation) == ("anonymize", 1)
    shown = await pipe.store.read(row.display_key)
    assert shown != data and decode(shown).size == (64, 48)
    out = (await pipe.runs(img))["anonymize"].output
    assert (out["faces"], out["plates"], len(out["regions"])) == (1, 0, 1)


async def test_no_detection_leaves_no_display_and_renditions_from_the_original(pipe):
    use_anonymize(FakeDetector([]))
    coll = await pipe.collection({"anonymize": {}, "renditions": {}})
    img = await pipe.image(coll, picture())
    await pipe.run(img)
    row = await pipe.row(img)
    assert (await pipe.status(img)) == {"anonymize": "completed", "renditions": "completed"}
    assert row.display_key is None
    assert {r.source_generation for r in (await pipe.renditions(img)).values()} == {0}


async def test_renditions_rerun_from_display(pipe):
    """Renditions first cut from the original; enabling ``anonymize`` publishes
    a display copy and the renditions are cut again, from it."""
    use_anonymize(FakeDetector([FACE]))
    coll = await pipe.collection({"renditions": {}})
    data = picture()
    img = await pipe.image(coll, data)
    await pipe.run(img)
    first = await pipe.renditions(img)
    assert {r.source_generation for r in first.values()} == {0}

    async with pipe.db_state.session_factory() as s:
        await s.execute(
            update(Collection)
            .where(Collection.id == coll.id)
            .values(pipeline_config={"steps": {"anonymize": {}, "renditions": {}}})
        )
        await s.commit()
    await pipe.run(img)

    row = await pipe.row(img)
    assert row.display_key is not None and row.display_generation == 1
    again = await pipe.renditions(img)
    assert {r.source_generation for r in again.values()} == {1}
    display = await pipe.store.read(row.display_key)
    medium = await pipe.store.read(again["medium"].storage_key)
    assert again["medium"].storage_key != first["medium"].storage_key
    # The rendition is the blurred picture, not the original.
    assert _distance(medium, display) < _distance(medium, data)


async def test_original_route_permission(client, storage, tmp_path):
    use_anonymize(FakeDetector([FACE]))
    pipe = await make_pipe(tmp_path, db_state=client.db_state)
    coll = collection(
        f"anon-{uuid.uuid4().hex[:6]}",
        Visibility.PUBLIC,
        pipeline_config={"steps": {"anonymize": {}, "renditions": {}}},
    )
    async with client.db_state.session_factory() as s:
        s.add(coll)
        await s.flush()
        s.add(share(coll, EDITOR, "edit"))
        await s.commit()
    data = picture()
    img = await pipe.image(coll, data)
    await pipe.run(img)
    row = await pipe.row(img)
    shown = await pipe.store.read(row.display_key)
    base = f"/api/images/images/{img}"

    async def get(path: str, hdrs: dict) -> tuple[int, bytes]:
        got = await client.get(f"{base}{path}", headers=hdrs)
        return got.status_code, got.content

    # The owner and an images.originals.view holder reach the original...
    assert await get("/original", headers(OWNER)) == (200, data)
    assert await get("/original", ORIGINALS) == (200, data)
    # ...an edit share and images.manage alone do not, and nor does the public.
    assert (await get("/original", headers(EDITOR)))[0] == 403
    assert (await get("/original", headers(MANAGER)))[0] == 403
    public = f"/api/images/public/c/{coll.slug}/images/{img}"
    assert (await client.get(f"{public}/original")).status_code == 403
    # Everyone else sees the blurred display copy.
    assert await get("/display", headers(EDITOR)) == (200, shown)
    assert (await client.get(f"{public}/display")).content == shown

    # Region coordinates are for those who can edit the collection.
    detail = (await client.get(base, headers=headers(EDITOR))).json()
    (run,) = [r for r in detail["step_runs"] if r["step"] == "anonymize"]
    assert run["output_visible"] is True and run["output"]["faces"] == 1
    detail = (await client.get(base, headers=headers(VIEWER))).json()
    (run,) = [r for r in detail["step_runs"] if r["step"] == "anonymize"]
    assert run["output_visible"] is False and run["output"] is None


async def test_viewer_props_follow_the_gate(client, storage, tmp_path):
    """Until ``anonymize`` settles the display is withheld (``display_pending``)
    and the original is protected; afterwards the blurred copy is shown."""
    use_anonymize(FakeDetector([FACE]))
    pipe = await make_pipe(tmp_path, db_state=client.db_state)
    coll = collection(
        f"gate-{uuid.uuid4().hex[:6]}",
        Visibility.PRIVATE,
        pipeline_config={"steps": {"anonymize": {}, "renditions": {}}},
    )
    async with client.db_state.session_factory() as s:
        s.add(coll)
        await s.flush()
        s.add(share(coll, EDITOR, "edit"))
        await s.commit()
    img = await pipe.image(coll, picture())
    url = f"/admin/images/images/{img}"

    async def props(who: str) -> dict:
        got = await client.get(url, headers={**headers(who), **INERTIA})
        assert got.status_code == 200, got.text
        return got.json()["props"]

    for who, original in ((OWNER, True), (EDITOR, False)):
        got = await props(who)
        assert (got["display_pending"], got["can_view_original"]) == (True, original)
    await pipe.run(img)
    for who, original in ((OWNER, True), (EDITOR, False)):
        got = await props(who)
        assert (got["display_pending"], got["can_view_original"]) == (False, original)
