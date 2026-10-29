"""Groups: role order from the collection, CRUD, assignment through the image
PATCH, regroup by pattern, and who may do what."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sm_images.models import Collection, Group, Image
from sqlalchemy import select, update

from tests.access_support import image, share
from tests.stub_auth import as_user
from tests.upload_support import BASE, OLGA, all_rows, make_collection

IMAGES = "/api/images/images"
GROUPS = "/api/images/groups"
ROLES = ["point", "north", "east"]
PATTERN = r"(?P<group>[a-z0-9]+)_(?P<role>[a-z]+)(?=_|\.|$)"


async def seed(client, names, roles=ROLES):
    cid = await make_collection(client)
    async with client.db_state.session_factory() as s:
        coll = await s.get(Collection, uuid.UUID(cid))
        coll.group_roles = list(roles)
        base = datetime(2026, 1, 1, tzinfo=UTC)
        rows = []
        for i, name in enumerate(names):
            row = image(coll, name, created_at=base + timedelta(minutes=i))
            s.add(row)
            rows.append(row)
        await s.commit()
        return cid, {r.filename: str(r.id) for r in rows}


async def make_group(client, cid, key="G1", headers=OLGA):
    got = await client.post(f"{BASE}/{cid}/groups", json={"key": key}, headers=headers)
    assert got.status_code == 201, got.text
    return got.json()["id"]


async def put(client, image_id, headers=OLGA, **body):
    return await client.patch(f"{IMAGES}/{image_id}", json=body, headers=headers)


async def regroup(client, cid, headers=OLGA, **body):
    body.setdefault("pattern", PATTERN)
    return await client.post(f"{BASE}/{cid}/regroup", json=body, headers=headers)


async def rows_by_name(client):
    async with client.db_state.session_factory() as s:
        keys = {g.id: g.key for g in (await s.execute(select(Group))).scalars()}
        imgs = (await s.execute(select(Image))).scalars().all()
        return {i.filename: (keys.get(i.group_id), i.group_role) for i in imgs}


async def test_members_follow_collection_roles(uploads):
    cid, ids = await seed(uploads, ["a", "b", "c", "d", "e"])
    gid = await make_group(uploads, cid)
    bad = await put(uploads, ids["a"], group_id=gid, group_role="zeta")
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_role"
    for name, role in [("b", "east"), ("d", "point"), ("a", None), ("c", None), ("e", "north")]:
        got = await put(uploads, ids[name], group_id=gid, **({"group_role": role} if role else {}))
        assert got.status_code == 200, got.text
    got = (await uploads.get(f"{GROUPS}/{gid}", headers=OLGA)).json()
    # point, north, east; then the role-less ones by creation time
    assert [m["filename"] for m in got["members"]] == ["d", "e", "b", "a", "c"]
    assert got["image_count"] == 5


async def test_unlisted_roles_sort_after_listed_then_by_name(uploads):
    """A role the collection stopped listing still shows, after the listed ones."""
    cid, ids = await seed(uploads, ["a", "b", "c", "d"])
    gid = await make_group(uploads, cid)
    async with uploads.db_state.session_factory() as s:
        for name, role in [("a", "zeta"), ("b", "alpha"), ("c", "north"), ("d", None)]:
            await s.execute(
                update(Image)
                .where(Image.id == uuid.UUID(ids[name]))
                .values(group_id=uuid.UUID(gid), group_role=role)
            )
        await s.commit()
    got = (await uploads.get(f"{GROUPS}/{gid}", headers=OLGA)).json()
    assert [m["filename"] for m in got["members"]] == ["c", "b", "a", "d"]


async def test_list_has_counts_and_a_preview_of_members(uploads):
    cid, ids = await seed(uploads, ["a", "b", "c"])
    one, two = await make_group(uploads, cid, "A"), await make_group(uploads, cid, "B")
    await put(uploads, ids["a"], group_id=one, group_role="north")
    await put(uploads, ids["b"], group_id=one, group_role="point")
    page = (await uploads.get(f"{BASE}/{cid}/groups", params={"limit": 1}, headers=OLGA)).json()
    assert [g["key"] for g in page["items"]] == ["A"] and page["next_cursor"] == "A"
    assert [m["filename"] for m in page["items"][0]["members"]] == ["b", "a"]
    rest = await uploads.get(
        f"{BASE}/{cid}/groups", params={"after": page["next_cursor"]}, headers=OLGA
    )
    assert [(g["id"], g["image_count"]) for g in rest.json()["items"]] == [(two, 0)]


async def test_crud_and_duplicate_keys(uploads):
    cid, _ = await seed(uploads, [])
    gid = await make_group(uploads, cid, " site-1 ")
    dup = await uploads.post(f"{BASE}/{cid}/groups", json={"key": "site-1"}, headers=OLGA)
    assert dup.status_code == 409 and dup.json()["code"] == "group_exists"
    other = await make_group(uploads, cid, "site-2")
    clash = await uploads.patch(f"{GROUPS}/{other}", json={"key": "site-1"}, headers=OLGA)
    assert clash.status_code == 409
    done = await uploads.patch(
        f"{GROUPS}/{gid}", json={"name": "North field", "key": "site-1"}, headers=OLGA
    )
    assert done.status_code == 200 and done.json()["name"] == "North field"
    cleared = await uploads.patch(f"{GROUPS}/{gid}", json={"name": None}, headers=OLGA)
    assert cleared.json()["name"] is None
    assert (await uploads.delete(f"{GROUPS}/{gid}", headers=OLGA)).status_code == 204
    assert (await uploads.get(f"{GROUPS}/{gid}", headers=OLGA)).status_code == 404


async def test_delete_group_frees_its_images_trashed_ones_too(uploads):
    cid, ids = await seed(uploads, ["a", "b"])
    gid = await make_group(uploads, cid)
    await put(uploads, ids["a"], group_id=gid, group_role="point")
    await put(uploads, ids["b"], group_id=gid, group_role="north")
    assert (await uploads.delete(f"{IMAGES}/{ids['b']}", headers=OLGA)).status_code == 204
    assert (await uploads.delete(f"{GROUPS}/{gid}", headers=OLGA)).status_code == 204
    rows = await all_rows(uploads, Image, include_deleted=True)
    assert {(r.filename, r.group_id, r.group_role) for r in rows} == {
        ("a", None, None),
        ("b", None, None),
    }
    assert await all_rows(uploads, Group) == []


async def test_image_patch_group_must_be_in_the_same_collection(uploads):
    _, ids = await seed(uploads, ["a"])
    other_cid, _ = await seed(uploads, [])
    foreign = await make_group(uploads, other_cid)
    got = await put(uploads, ids["a"], group_id=foreign)
    assert got.status_code == 422 and got.json()["code"] == "group_not_found"
    missing = await put(uploads, ids["a"], group_id=str(uuid.uuid4()))
    assert (missing.status_code, missing.json()) == (got.status_code, got.json())
    assert (await all_rows(uploads, Image))[0].group_id is None


async def test_image_patch_roles_and_clearing(uploads):
    cid, ids = await seed(uploads, ["a"])
    gid = await make_group(uploads, cid)
    got = await put(uploads, ids["a"], group_id=gid, group_role="NORTH")
    assert (got.json()["group_id"], got.json()["group_role"]) == (gid, "north")
    assert (await put(uploads, ids["a"], group_role=None)).json()["group_role"] is None
    assert (await put(uploads, ids["a"], group_role="east")).json()["group_role"] == "east"
    assert (await put(uploads, ids["a"], group_id=None)).json()["group_role"] is None
    assert (await put(uploads, ids["a"], group_role="east")).status_code == 422
    assert (await put(uploads, ids["a"])).status_code == 422


async def test_a_collection_without_roles_takes_any_role(uploads):
    cid, ids = await seed(uploads, ["a"], roles=[])
    gid = await make_group(uploads, cid)
    got = await put(uploads, ids["a"], group_id=gid, group_role="Left Bank")
    assert got.status_code == 200 and got.json()["group_role"] == "left bank"


async def test_regroup_assigns_groups_and_roles_and_is_idempotent(uploads):
    names = ["s1_point.jpg", "s1_North.jpg", "s2_point.jpg", "s2_up.jpg", "loose.jpg"]
    cid, _ = await seed(uploads, names)
    dry = await regroup(uploads, cid, dry_run=True)
    assert dry.status_code == 200, dry.text
    assert dry.json()["assigned"] == 4 and dry.json()["groups_created"] == 2
    assert await all_rows(uploads, Group) == []  # preview writes nothing
    first = (await regroup(uploads, cid)).json()
    assert (first["scanned"], first["matched"], first["no_match"]) == (5, 4, 1)
    assert (first["assigned"], first["groups_created"]) == (4, 2)
    assert await rows_by_name(uploads) == {
        "s1_point.jpg": ("s1", "point"),
        "s1_North.jpg": ("s1", "north"),
        "s2_point.jpg": ("s2", "point"),
        "s2_up.jpg": ("s2", None),  # "up" is not a listed role: dropped, group kept
        "loose.jpg": (None, None),
    }
    again = (await regroup(uploads, cid)).json()
    assert (again["assigned"], again["unchanged"], again["groups_created"]) == (0, 4, 0)


async def test_regroup_leaves_manual_groups_unless_reassign(uploads):
    cid, ids = await seed(uploads, ["s1_point.jpg", "s2_point.jpg"])
    manual = await make_group(uploads, cid, "manual")
    await put(uploads, ids["s1_point.jpg"], group_id=manual, group_role="east")
    got = (await regroup(uploads, cid)).json()
    assert (got["assigned"], got["already_grouped"]) == (1, 1)
    assert (await rows_by_name(uploads))["s1_point.jpg"] == ("manual", "east")
    got = (await regroup(uploads, cid, reassign=True)).json()
    assert got["assigned"] == 1
    assert (await rows_by_name(uploads))["s1_point.jpg"] == ("s1", "point")


async def test_regroup_keeps_the_role_when_the_pattern_gives_none(uploads):
    cid, ids = await seed(uploads, ["s1.jpg"])
    manual = await make_group(uploads, cid, "manual")
    await put(uploads, ids["s1.jpg"], group_id=manual, group_role="east")
    await regroup(uploads, cid, pattern=r"(?P<group>[a-z0-9]+)\.", reassign=True)
    assert (await rows_by_name(uploads))["s1.jpg"] == ("s1", "east")


async def test_regroup_more_images_than_one_chunk(uploads, monkeypatch):
    from sm_images import constants

    monkeypatch.setattr(constants, "REGROUP_CHUNK", 3)
    names = [f"s{i % 4}_{ROLES[i % 3]}_{i}.jpg" for i in range(10)]
    cid, _ = await seed(uploads, names)
    got = (await regroup(uploads, cid)).json()
    assert (got["scanned"], got["assigned"], got["groups_created"]) == (10, 10, 4)
    assert all(g is not None for g, _ in (await rows_by_name(uploads)).values())


async def test_regroup_refuses_bad_patterns_and_reports_timeouts(uploads, monkeypatch):
    cid, _ = await seed(uploads, ["a_point.jpg"])
    for pattern in ("(unclosed", r"[a-z]+_(?P<role>[a-z]+)"):
        got = await regroup(uploads, cid, pattern=pattern)
        assert got.status_code == 422 and got.json()["code"] == "invalid_pattern"
    from sm_images.imports import filename_pattern as fp

    monkeypatch.setattr(fp, "MATCH_TIMEOUT_SECONDS", 0.001)
    cid2, _ = await seed(uploads, ["a" * 40 + "!.jpg"])
    got = (await regroup(uploads, cid2, pattern=r"(?P<group>(a|aa)+)_(?P<role>x)$")).json()
    assert (got["timed_out"], got["no_match"], got["assigned"]) == (1, 0, 0)


async def test_regroup_over_budget_writes_nothing(uploads, monkeypatch):
    from sm_images import constants

    monkeypatch.setattr(constants, "REGROUP_BUDGET_SECONDS", -1.0)
    cid, _ = await seed(uploads, ["s1_point.jpg"])
    got = await regroup(uploads, cid)
    assert got.status_code == 422 and got.json()["code"] == "regroup_too_slow"
    assert await all_rows(uploads, Group) == []


async def test_edit_share_manages_groups_and_view_share_cannot(uploads):
    cid, ids = await seed(uploads, ["a"])
    gid = await make_group(uploads, cid)
    async with uploads.db_state.session_factory() as s:
        coll = await s.get(Collection, uuid.UUID(cid))
        s.add_all([share(coll, "eddie", "edit"), share(coll, "vic", "view")])
        await s.commit()
    editor = as_user("eddie", ("images.view",))
    viewer = as_user("vic", ("images.view",))
    stranger = as_user("sam", ("images.view",))
    assert (await make_group(uploads, cid, "E", editor)) is not None
    assert (await put(uploads, ids["a"], editor, group_id=gid)).status_code == 200
    assert (await regroup(uploads, cid, editor)).status_code == 200
    assert (await uploads.get(f"{GROUPS}/{gid}", headers=viewer)).status_code == 200
    assert (await uploads.get(f"{BASE}/{cid}/groups", headers=viewer)).status_code == 200
    denied = [
        await uploads.post(f"{BASE}/{cid}/groups", json={"key": "X"}, headers=viewer),
        await uploads.patch(f"{GROUPS}/{gid}", json={"name": "x"}, headers=viewer),
        await uploads.delete(f"{GROUPS}/{gid}", headers=viewer),
        await regroup(uploads, cid, viewer),
        await put(uploads, ids["a"], viewer, group_id=None),
    ]
    assert [d.status_code for d in denied] == [403] * 5
    assert (await uploads.get(f"{GROUPS}/{gid}", headers=stranger)).status_code == 404
