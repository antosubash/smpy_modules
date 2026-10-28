"""The console screens' props, and the URLs the image API hands them."""

from __future__ import annotations

import uuid

from sm_images.models import Image, Rendition
from sqlalchemy import update

from tests.stub_auth import as_user
from tests.upload_support import BASE, OLGA, WRITER, all_rows, jpeg, make_collection, post_files

VIEWS = "/admin/images"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
MANAGER = as_user("mallory", ("images.view", "images.manage"))


def props(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["props"]


async def one_image(client) -> tuple[str, str]:
    cid = await make_collection(client)
    got = await post_files(client, cid, [("a.jpg", jpeg(), "image/jpeg")])
    assert got.status_code == 200, got.text
    return cid, got.json()["results"][0]["id"]


async def add_small(client, image_id: str, generation: int) -> None:
    async with client.db_state.session_factory() as s:
        s.add(
            Rendition(
                image_id=uuid.UUID(image_id),
                size="small",
                storage_key="k/small.jpg",
                width=8,
                height=6,
                source_generation=generation,
            )
        )
        await s.commit()


async def test_list_urls_are_versioned_and_thumb_waits_for_a_rendition(uploads):
    cid, iid = await one_image(uploads)
    page = (await uploads.get(f"{BASE}/{cid}/images", headers=OLGA)).json()
    (item,) = page["items"]
    assert item["thumb_url"] is None
    assert item["display_url"].startswith(f"/api/images/images/{iid}/display?v=")
    await add_small(uploads, iid, generation=0)
    (item,) = (await uploads.get(f"{BASE}/{cid}/images", headers=OLGA)).json()["items"]
    assert item["thumb_url"].startswith(f"/api/images/images/{iid}/r/small?v=")


async def test_a_rendition_of_an_older_display_copy_is_not_offered(uploads):
    cid, iid = await one_image(uploads)
    await add_small(uploads, iid, generation=0)
    async with uploads.db_state.session_factory() as s:
        await s.execute(update(Image).values(display_generation=1))
        await s.commit()
    (item,) = (await uploads.get(f"{BASE}/{cid}/images", headers=OLGA)).json()["items"]
    assert item["thumb_url"] is None


async def test_collections_screen_props(uploads):
    await make_collection(uploads)
    got = props(await uploads.get(f"{VIEWS}/", headers={**OLGA, **INERTIA}))
    assert [c["name"] for c in got["collections"]["items"]] == ["Trees"]
    assert got["can_create"] is True
    assert got["can_publish"] is False


async def test_collection_screen_rights(uploads):
    cid, _ = await one_image(uploads)
    mine = props(await uploads.get(f"{VIEWS}/{cid}", headers={**OLGA, **INERTIA}))
    assert mine["collection"]["id"] == cid
    assert mine["direct_upload_threshold"] == 20 * 1024 * 1024
    assert (mine["can_edit"], mine["can_manage"]) == (True, True)
    # Sharing is the owner's and needs the framework's own permission.
    assert mine["can_share"] is False
    owner = as_user("olga", ("images.view", "images.create", "sharing.share"))
    assert props(await uploads.get(f"{VIEWS}/{cid}", headers={**owner, **INERTIA}))["can_share"]


async def test_viewer_offers_the_original_unless_a_display_copy_protects_it(uploads):
    _, iid = await one_image(uploads)
    url = f"{VIEWS}/images/{iid}"
    assert props(await uploads.get(url, headers={**OLGA, **INERTIA}))["can_view_original"] is True
    assert props(await uploads.get(url, headers={**MANAGER, **INERTIA}))["can_view_original"]
    (row,) = await all_rows(uploads)
    async with uploads.db_state.session_factory() as s:
        await s.execute(
            update(Image)
            .where(Image.id == row.id)
            .values(display_key="d.jpg", display_generation=1)
        )
        await s.commit()
    # ``images.manage`` alone never reaches a protected original; the owner does.
    assert (
        props(await uploads.get(url, headers={**MANAGER, **INERTIA}))["can_view_original"] is False
    )
    assert props(await uploads.get(url, headers={**OLGA, **INERTIA}))["can_view_original"] is True


async def test_screens_hide_a_collection_the_caller_may_not_open(uploads):
    cid, iid = await one_image(uploads)
    stranger = as_user("sam", ("images.view",))
    assert (await uploads.get(f"{VIEWS}/{cid}", headers={**stranger, **INERTIA})).status_code == 404
    got = await uploads.get(f"{VIEWS}/images/{iid}", headers={**stranger, **INERTIA})
    assert got.status_code == 404


async def test_an_images_refusal_on_a_screen_is_the_hosts_error_page(uploads):
    """The framework's own 404 (an id the policy hides) already gets the host's
    page; this is the one images raises itself (``ImagesError``)."""
    from sm_images.errors import NotFound

    @uploads.app.get(f"{VIEWS}/x/boom")
    async def boom():
        raise NotFound("gone")

    screen = await uploads.get(f"{VIEWS}/x/boom", headers={**OLGA, **INERTIA})
    assert screen.status_code == 404
    assert screen.json().get("component") and "detail" not in screen.json()


async def _seed_run(client, iid: str) -> None:
    from sm_images.models import StepRun, StepStatus
    from sqlalchemy import delete

    async with client.db_state.session_factory() as s:
        await s.execute(delete(StepRun).where(StepRun.image_id == uuid.UUID(iid)))
        s.add(
            StepRun(
                image_id=uuid.UUID(iid),
                step="exif",
                status=StepStatus.FAILED,
                step_version=2,
                error_code="boom",
                error_message="/srv/internal/path blew up",
                output={"regions": [[1, 2, 3, 4]]},
            )
        )
        await s.commit()


async def test_an_editor_sees_step_output_and_messages_a_viewer_does_not(uploads):
    publisher = as_user("olga", (*WRITER, "images.publish"))
    cid = await make_collection(uploads, publisher, visibility="internal")
    got = await post_files(uploads, cid, [("a.jpg", jpeg(), "image/jpeg")])
    iid = got.json()["results"][0]["id"]
    await _seed_run(uploads, iid)
    url = f"{VIEWS}/images/{iid}"
    api = f"/api/images/images/{iid}"
    viewer = as_user("sam", ("images.view",))

    for headers in (OLGA, MANAGER):  # the owner; images.manage
        page = props(await uploads.get(url, headers={**headers, **INERTIA}))
        (run,) = page["image"]["step_runs"]
        assert run["output"] == {"regions": [[1, 2, 3, 4]]}
        assert run["error_message"] == "/srv/internal/path blew up"
        assert run["step_version"] == 2 and run["error_code"] == "boom"
        assert (await uploads.get(api, headers=headers)).json()["step_runs"][0]["output"]

    page = props(await uploads.get(url, headers={**viewer, **INERTIA}))
    (run,) = page["image"]["step_runs"]
    assert run["step"] == "exif" and run["status"] == "failed" and run["error_code"] == "boom"
    assert run["output"] is None and run["error_message"] is None
    (api_run,) = (await uploads.get(api, headers=viewer)).json()["step_runs"]
    assert api_run["output"] is None and api_run["error_message"] is None

    listed = await uploads.get(f"/api/images/collections/{cid}/images", headers=OLGA)
    assert listed.json()["items"][0]["step_runs"] is None
