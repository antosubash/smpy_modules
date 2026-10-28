"""Listing collections: the filters, the cursor, the bounds."""

from __future__ import annotations

import pytest
from sm_images.models import Collection
from sqlalchemy import select

from tests.access_support import share
from tests.test_collections_api import BASE, PUBLISHER, WRITER, create, h


async def _seed_list(client):
    """olga: priv, int, pub; sam: sam-priv, sam-pub; sam shares sam-priv with olga."""
    for who, slug, vis in (
        ("olga", "o-priv", "private"),
        ("olga", "o-int", "internal"),
        ("olga", "o-pub", "public"),
        ("sam", "s-priv", "private"),
        ("sam", "s-pub", "public"),
        ("sam", "s-shared", "private"),
    ):
        r = await create(client, who=who, perms=PUBLISHER, name=slug, slug=slug, visibility=vis)
        assert r.status_code == 201, r.text
    async with client.db_state.session_factory() as s:
        coll = (
            (await s.execute(select(Collection).where(Collection.slug == "s-shared")))
            .scalars()
            .one()
        )
        s.add(share(coll, "olga", "view"))
        await s.commit()


async def slugs(client, who="olga", perms=WRITER, **params):
    r = await client.get(BASE, params=params, headers=h(who, perms))
    assert r.status_code == 200, r.text
    return sorted(i["slug"] for i in r.json()["items"])


@pytest.mark.parametrize(
    ("filter_", "expected"),
    [
        ("owned", ["o-int", "o-priv", "o-pub"]),
        ("shared", ["s-shared"]),
        ("internal", ["o-int"]),
        ("public", ["o-pub", "s-pub"]),
        ("all", ["o-int", "o-priv", "o-pub", "s-pub", "s-shared"]),
    ],
)
async def test_filters_are_anded_with_the_policy(client, filter_, expected):
    await _seed_list(client)
    assert await slugs(client, filter=filter_) == expected


async def test_default_filter_is_all_and_unknown_is_422(client):
    await _seed_list(client)
    assert len(await slugs(client)) == 5
    r = await client.get(BASE, params={"filter": "nope"}, headers=h("olga"))
    assert r.status_code == 422


async def test_a_manager_sees_everything_under_all_but_only_own_under_owned(client):
    await _seed_list(client)
    mgr = (*WRITER, "images.manage")
    assert len(await slugs(client, who="max", perms=mgr, filter="all")) == 6
    assert await slugs(client, who="max", perms=mgr, filter="owned") == []


async def test_cursor_pages_newest_first_without_gaps_and_counts_once(client):
    for n in range(5):
        assert (await create(client, name=f"c{n}", slug=f"c{n}")).status_code == 201
    seen_slugs: list[str] = []
    cursor = None
    totals = []
    pages = 0
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (await client.get(BASE, params=params, headers=h("olga"))).json()
        totals.append(body["total"])
        seen_slugs += [i["slug"] for i in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3
    assert totals == [5, None, None]
    assert sorted(seen_slugs) == [f"c{n}" for n in range(5)]
    assert len(set(seen_slugs)) == 5
    # newest first
    assert seen_slugs == [f"c{n}" for n in (4, 3, 2, 1, 0)]


async def test_a_cursor_survives_deletion_of_its_row(client):
    ids = [(await create(client, name=f"c{n}", slug=f"c{n}")).json()["id"] for n in range(4)]
    first = (await client.get(BASE, params={"limit": 2}, headers=h("olga"))).json()
    assert [i["slug"] for i in first["items"]] == ["c3", "c2"]
    await client.delete(f"{BASE}/{ids[2]}", headers=h("olga"))  # the cursor's own row
    rest = (
        await client.get(
            BASE, params={"limit": 2, "cursor": first["next_cursor"]}, headers=h("olga")
        )
    ).json()
    assert [i["slug"] for i in rest["items"]] == ["c1", "c0"]


@pytest.mark.parametrize("cursor", ["!!!", "bm9wZQ"])
async def test_bad_cursor_is_422(client, cursor):
    r = await client.get(BASE, params={"cursor": cursor}, headers=h("olga"))
    assert r.status_code == 422


@pytest.mark.parametrize("limit", [0, 101])
async def test_limit_is_bounded(client, limit):
    assert (await client.get(BASE, params={"limit": limit}, headers=h("olga"))).status_code == 422


async def test_an_expired_share_is_not_shared(client):
    from datetime import UTC, datetime, timedelta

    await create(client, who="sam", name="theirs", slug="theirs")
    async with client.db_state.session_factory() as s:
        coll = (await s.execute(select(Collection))).scalars().one()
        s.add(share(coll, "olga", "view", expires_at=datetime.now(UTC) - timedelta(days=1)))
        await s.commit()
    assert await slugs(client, filter="shared") == []
    assert await slugs(client) == []


async def test_equal_created_at_ties_break_by_id_across_a_page_boundary(client):
    from datetime import UTC, datetime

    from sqlalchemy import update

    for n in range(5):
        await create(client, name=f"t{n}", slug=f"t{n}")
    async with client.db_state.session_factory() as s:
        await s.execute(update(Collection).values(created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        await s.commit()
    got: list[str] = []
    cursor = None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (await client.get(BASE, params=params, headers=h("olga"))).json()
        got += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(got) == 5
    assert len(set(got)) == 5
    assert got == sorted(got, reverse=True)


def test_a_naive_cursor_is_read_as_utc():
    import base64
    import uuid
    from datetime import UTC

    from sm_images.services import cursor

    raw = f"2026-01-01T00:00:00|{uuid.uuid4()}".encode()
    forged = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    moment, _ = cursor.decode(forged)
    assert moment.tzinfo is UTC
