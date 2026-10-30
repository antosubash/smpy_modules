# ruff: noqa: F811
"""A withheld image is indistinguishable from an absent one (Task 27 fix 3).

Original downloads answered 403 for a withheld image and 404 for an unknown
id, which says the image exists. Groups are named by the metadata of their
images, so a group of withheld images is withheld too.
"""

from __future__ import annotations

import uuid

import pytest
from sm_images.core.storage import ImageStore
from sm_images.core.tenancy import DEFAULT_TENANT, tenant_scope
from sm_images.models import Group, Image
from sqlalchemy import select, update

from tests.support.access import OWNER, STRANGER, headers
from tests.web.collections.test_viewer_stats import blur_installed, seeded  # noqa: F401


async def _pending_id(client, storage) -> uuid.UUID:
    with tenant_scope(DEFAULT_TENANT):
        async with client.db_state.session_factory() as s:
            row = (
                await s.execute(select(Image).where(Image.filename == "pending.jpg"))
            ).scalar_one()
    await ImageStore(storage).put(
        row.storage_key, b"secret-bytes", content_type="image/jpeg", size=12
    )
    return row.id


def _urls(seeded, image_id):
    return {
        "admin": f"/api/images/images/{image_id}/original",
        "public": f"/api/images/public/c/{seeded.slug}/images/{image_id}/original",
    }


def _shape(response):
    keep = ("cache-control", "content-type", "etag", "content-length")
    return (
        response.status_code,
        response.text,
        {k: v for k, v in response.headers.items() if k in keep},
    )


@pytest.mark.parametrize("method", ["get", "head"])
@pytest.mark.parametrize("surface", ["admin", "public"])
async def test_a_withheld_original_looks_like_an_absent_one(
    client, storage, seeded, method, surface
):
    pending = await _pending_id(client, storage)
    call = getattr(client, method)
    for who in (None, STRANGER):
        got = await call(_urls(seeded, pending)[surface], headers=headers(who))
        absent = await call(_urls(seeded, uuid.uuid4())[surface], headers=headers(who))
        if surface == "admin" and who is None:
            continue  # the admin route needs a session at all
        assert got.status_code == 404, (who, got.status_code)
        assert _shape(got) == _shape(absent)


async def test_an_editor_still_gets_the_withheld_original(client, storage, seeded):
    pending = await _pending_id(client, storage)
    got = await client.get(_urls(seeded, pending)["admin"], headers=headers(OWNER))
    assert got.status_code == 200 and got.content == b"secret-bytes"


async def test_a_group_of_withheld_images_is_hidden_from_a_viewer(client, seeded):
    with tenant_scope(DEFAULT_TENANT):
        async with client.db_state.session_factory() as s:
            group = Group(collection_id=seeded.id, key="sensitive-site-123")
            s.add(group)
            await s.flush()
            await s.execute(
                update(Image).where(Image.filename == "pending.jpg").values(group_id=group.id)
            )
            await s.commit()
            group_id = group.id
    base = f"/api/images/collections/{seeded.id}/groups"
    viewer = await client.get(base, headers=headers(STRANGER))
    assert "sensitive-site-123" not in viewer.text
    assert viewer.json()["items"] == []
    detail = await client.get(f"/api/images/groups/{group_id}", headers=headers(STRANGER))
    assert detail.status_code == 404 and "sensitive" not in detail.text
    owner = await client.get(base, headers=headers(OWNER))
    assert [g["key"] for g in owner.json()["items"]] == ["sensitive-site-123"]
    assert (
        await client.get(f"/api/images/groups/{group_id}", headers=headers(OWNER))
    ).status_code == 200


async def _ids(client, seeded) -> dict[str, uuid.UUID]:
    """The safe and the pending image, each in a group of its own."""
    with tenant_scope(DEFAULT_TENANT):
        async with client.db_state.session_factory() as s:
            out: dict[str, uuid.UUID] = {}
            for name in ("safe", "pending"):
                group = Group(collection_id=seeded.id, key=f"{name}-site")
                s.add(group)
                await s.flush()
                img = (
                    await s.execute(select(Image).where(Image.filename == f"{name}.jpg"))
                ).scalar_one()
                img.group_id = group.id
                out[name], out[f"{name}_group"] = img.id, group.id
            await s.commit()
    return out


WRITES = [
    ("PATCH", "/api/images/images/{}", {"lat": 1.0, "lng": 2.0}, "image"),
    ("DELETE", "/api/images/images/{}", None, "image"),
    ("POST", "/api/images/images/{}/reprocess", {}, "image"),
    ("PATCH", "/api/images/groups/{}", {"name": "x"}, "group"),
    ("DELETE", "/api/images/groups/{}", None, "group"),
]


@pytest.mark.parametrize(("method", "path", "body", "kind"), WRITES)
async def test_a_viewer_write_on_a_withheld_target_is_the_absent_404(
    client, seeded, method, path, body, kind
):
    """S3: the action's 403 would say the id exists. A viewer (who cannot
    edit) gets the absent 404 for a withheld image or group, and the 403 only
    for one they can see."""
    ids = await _ids(client, seeded)
    key = "pending" if kind == "image" else "pending_group"
    shown = "safe" if kind == "image" else "safe_group"
    kw = {} if body is None else {"json": body}

    async def call(target):
        return await client.request(method, path.format(target), headers=headers(STRANGER), **kw)

    withheld, absent = await call(ids[key]), await call(uuid.uuid4())
    assert withheld.status_code == 404, withheld.text
    assert _shape(withheld) == _shape(absent)
    visible = await call(ids[shown])
    assert visible.status_code == 403, visible.text
