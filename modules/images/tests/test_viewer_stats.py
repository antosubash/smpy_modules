"""Collection counts and box for someone who may only view (Task 27 fix 1).

The stored counters and box cover every live image. A viewer must not learn the
place or the existence of an image whose picture is withheld (redaction not yet
settled), so every viewer-facing surface recomputes them over the display-safe
images; an editor keeps the raw numbers.
"""

from __future__ import annotations

import uuid

import pytest
from sm_images.contracts import get_collection, list_collections
from sm_images.models import Image, StepRun, Visibility
from sm_images.models.enums import StepStatus
from sm_images.services import stats
from sm_images.tenancy import DEFAULT_TENANT, tenant_scope
from sqlalchemy import update

from tests.access_support import OWNER, STRANGER, collection, headers, image, principal
from tests.pipeline_support import Blur, use_steps

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
SAFE = (10.0, 20.0)
HIDDEN = (-60.0, 150.0)
SAFE_BOX = [SAFE[1], SAFE[0], SAFE[1], SAFE[0]]
RAW_BOX = [SAFE[1], HIDDEN[0], HIDDEN[1], SAFE[0]]


@pytest.fixture
def blur_installed():
    use_steps(Blur())
    yield
    use_steps()


@pytest.fixture
async def seeded(client, blur_installed):
    """A public collection with one settled image and one still pending, far away."""
    coll = collection(f"v-{uuid.uuid4().hex[:8]}", Visibility.PUBLIC, OWNER)
    coll.pipeline_config = {"steps": {"acme.blur": {}}}
    with tenant_scope(DEFAULT_TENANT):
        async with client.db_state.session_factory() as s:
            s.add(coll)
            await s.flush()
            safe = image(coll, "safe.jpg", lat=SAFE[0], lng=SAFE[1])
            pending = image(coll, "pending.jpg", lat=HIDDEN[0], lng=HIDDEN[1])
            s.add_all([safe, pending])
            await s.flush()
            s.add(
                StepRun(
                    image_id=safe.id, step="acme.blur", status=StepStatus.COMPLETED, step_version=1
                )
            )
            await stats.recompute(s, coll.id)
            await s.commit()
    return coll


async def test_public_page_ignores_a_pending_image(client, seeded):
    got = await client.get(f"/images/c/{seeded.slug}", headers=INERTIA)
    shown = got.json()["props"]["collection"]
    assert shown["bbox"] == SAFE_BOX
    assert (shown["image_count"], shown["located_count"]) == (1, 1)


async def test_collection_api_gates_a_viewer_but_not_the_owner(client, seeded):
    url = f"/api/images/collections/{seeded.id}"
    viewer = (await client.get(url, headers=headers(STRANGER))).json()
    assert viewer["bbox"] == SAFE_BOX
    assert (viewer["image_count"], viewer["located_count"]) == (1, 1)
    owner = (await client.get(url, headers=headers(OWNER))).json()
    assert (owner["image_count"], owner["located_count"]) == (2, 2)
    assert owner["bbox"] == RAW_BOX


async def test_collection_list_gates_a_viewer(client, seeded):
    page = (await client.get("/api/images/collections", headers=headers(STRANGER))).json()
    (item,) = [i for i in page["items"] if i["id"] == str(seeded.id)]
    assert item["bbox"] == SAFE_BOX and item["image_count"] == 1


async def test_console_pages_gate_a_viewer(client, seeded):
    hdrs = {**headers(STRANGER), **INERTIA}
    detail = await client.get(f"/admin/images/{seeded.id}", headers=hdrs)
    assert detail.json()["props"]["collection"]["bbox"] == SAFE_BOX
    listing = await client.get("/admin/images/", headers=hdrs)
    items = listing.json()["props"]["collections"]["items"]
    (item,) = [i for i in items if i["id"] == str(seeded.id)]
    assert item["bbox"] == SAFE_BOX


async def test_contracts_gate_a_viewer(client, seeded):
    async with client.db_state.session_factory() as db:
        got = await get_collection(DEFAULT_TENANT, seeded.id, principal(STRANGER), db=db)
        assert got.bbox == SAFE_BOX and got.image_count == 1
        page = await list_collections(DEFAULT_TENANT, principal(STRANGER), db=db)
        (item,) = [i for i in page.items if i.id == seeded.id]
        assert item.bbox == SAFE_BOX
        mine = await get_collection(DEFAULT_TENANT, seeded.id, principal(OWNER), db=db)
        assert mine.image_count == 2


async def test_a_trashed_image_does_not_count(client, seeded):
    async with client.db_state.session_factory() as s:
        with tenant_scope(DEFAULT_TENANT):
            await s.execute(
                update(Image).where(Image.filename == "safe.jpg").values(is_deleted=True)
            )
            await s.commit()
    got = await client.get(f"/images/c/{seeded.slug}", headers=INERTIA)
    shown = got.json()["props"]["collection"]
    assert shown["bbox"] is None and shown["image_count"] == 0


# ---- fix round 2: the image reads --------------------------------------------


async def _group_pending(client, seeded):
    """Put both images in one group; returns (group id, pending image id)."""
    from sm_images.models import Group
    from sqlalchemy import select

    with tenant_scope(DEFAULT_TENANT):
        async with client.db_state.session_factory() as s:
            group = Group(collection_id=seeded.id, key="site")
            s.add(group)
            await s.flush()
            await s.execute(
                update(Image).where(Image.collection_id == seeded.id).values(group_id=group.id)
            )
            pending = (
                await s.execute(select(Image.id).where(Image.filename == "pending.jpg"))
            ).scalar_one()
            await s.commit()
            return group.id, pending


async def test_image_list_hides_a_pending_image_from_a_viewer(client, seeded):
    url = f"/api/images/collections/{seeded.id}/images"
    viewer = (await client.get(url, headers=headers(STRANGER))).json()
    assert viewer["total"] == 1
    assert [i["lat"] for i in viewer["items"]] == [SAFE[0]]
    assert "pending.jpg" not in str(viewer)
    only_far = await client.get(url + "?has_location=true&limit=1", headers=headers(STRANGER))
    assert only_far.json()["total"] == 1
    owner = (await client.get(url, headers=headers(OWNER))).json()
    assert owner["total"] == 2


async def test_image_detail_of_a_pending_image_is_404_for_a_viewer(client, seeded):
    _, pending = await _group_pending(client, seeded)
    url = f"/api/images/images/{pending}"
    assert (await client.get(url, headers=headers(STRANGER))).status_code == 404
    assert (await client.get(url, headers=headers(OWNER))).status_code == 200
    page = await client.get(
        f"/admin/images/images/{pending}", headers={**headers(STRANGER), **INERTIA}
    )
    assert page.status_code == 404


async def test_groups_count_and_show_only_ready_members_to_a_viewer(client, seeded):
    group_id, pending = await _group_pending(client, seeded)
    base = f"/api/images/collections/{seeded.id}/groups"
    for url in (base, f"/api/images/groups/{group_id}"):
        got = (await client.get(url, headers=headers(STRANGER))).json()
        row = got["items"][0] if "items" in got else got
        assert row["image_count"] == 1
        assert [m["lat"] for m in row["members"]] == [SAFE[0]]
        assert str(pending) not in str(got)
    owner = (await client.get(base, headers=headers(OWNER))).json()["items"][0]
    assert owner["image_count"] == 2


async def test_pipeline_overview_is_editor_only(client, seeded):
    url = f"/api/images/collections/{seeded.id}/pipeline"
    assert (await client.get(url, headers=headers(STRANGER))).status_code in (403, 404)
    assert (await client.get(url, headers=headers(OWNER))).status_code == 200
