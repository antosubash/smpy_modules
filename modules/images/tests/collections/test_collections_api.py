"""Collection CRUD, slug rules, visibility and its publish gate, events, listing."""

from __future__ import annotations

import pytest
from sm_images.contracts.events import CollectionDeleted, CollectionVisibilityChanged
from sm_images.models import Collection, Visibility
from sqlalchemy import select

from tests.support.access import share
from tests.support.stub_auth import as_user, user_uuid

BASE = "/api/images/collections"
WRITER = ("images.view", "images.create")
PUBLISHER = (*WRITER, "images.publish")


def h(who: str, perms=WRITER):
    return as_user(who, perms)


async def create(client, who="olga", perms=WRITER, **body):
    body.setdefault("name", "Trees")
    return await client.post(BASE, json=body, headers=h(who, perms))


async def test_create_generates_a_slug_and_owns_it(client):
    r = await create(client, name="  Street Trees 2026!  ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Street Trees 2026!"
    assert body["slug"] == "street-trees-2026"
    assert body["owner_id"] == user_uuid("olga")
    assert body["visibility"] == "private"
    assert body["is_owner"] is True
    assert (body["image_count"], body["located_count"], body["bbox"]) == (0, 0, None)


async def test_generated_slug_that_collides_gets_a_suffix(client):
    first = (await create(client, name="Trees")).json()
    second = (await create(client, name="Trees")).json()
    assert first["slug"] == "trees"
    assert second["slug"] != "trees"
    assert second["slug"].startswith("trees-")


async def test_explicit_slug_conflict_is_409(client):
    assert (await create(client, slug="mine")).status_code == 201
    r = await create(client, who="sam", slug="mine")
    assert r.status_code == 409


async def test_trashed_collection_still_holds_its_slug(client):
    made = (await create(client, slug="gone")).json()
    assert (await client.delete(f"{BASE}/{made['id']}", headers=h("olga"))).status_code == 204
    assert (await create(client, slug="gone")).status_code == 409


@pytest.mark.parametrize("slug", ["Upper", "has space", "x" * 81, "", "ünï"])
async def test_bad_slug_is_422(client, slug):
    assert (await create(client, slug=slug)).status_code == 422


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
async def test_bad_name_is_422(client, name):
    assert (await create(client, name=name)).status_code == 422


async def test_create_needs_the_create_permission(client):
    r = await create(client, perms=("images.view",))
    assert r.status_code == 403


async def test_anonymous_is_401(client):
    assert (await client.get(BASE)).status_code == 401
    assert (await client.post(BASE, json={"name": "x"})).status_code == 401


async def test_get_patch_and_explicit_null_name_is_ignored(client):
    made = (await create(client, description="d")).json()
    url = f"{BASE}/{made['id']}"
    assert (await client.get(url, headers=h("olga"))).json()["name"] == "Trees"

    r = await client.patch(url, json={"name": None, "description": None}, headers=h("olga"))
    assert r.status_code == 200
    assert r.json()["name"] == "Trees"
    assert r.json()["description"] is None

    r = await client.patch(url, json={"name": " Oaks "}, headers=h("olga"))
    assert r.json()["name"] == "Oaks"
    assert r.json()["slug"] == "trees"  # a slug never follows the name


@pytest.mark.parametrize("body", [{"name": "   "}, {"visibility": "public"}, {"slug": "x"}])
async def test_patch_rejects_blank_name_and_visibility_and_slug(client, body):
    made = (await create(client)).json()
    r = await client.patch(f"{BASE}/{made['id']}", json=body, headers=h("olga"))
    assert r.status_code == 422


async def test_patch_by_an_edit_share_works_but_a_view_share_is_403(client):
    made = (await create(client)).json()
    async with client.db_state.session_factory() as s:
        coll = (await s.execute(select(Collection))).scalars().one()
        s.add_all([share(coll, "eddie", "edit"), share(coll, "vic", "view")])
        await s.commit()
    url = f"{BASE}/{made['id']}"
    assert (await client.patch(url, json={"name": "E"}, headers=h("eddie"))).status_code == 200
    assert (await client.patch(url, json={"name": "V"}, headers=h("vic"))).status_code == 403
    assert (await client.patch(url, json={"name": "S"}, headers=h("sam"))).status_code == 404
    # shares never delete
    assert (await client.delete(url, headers=h("eddie"))).status_code == 403


async def test_delete_is_soft_and_then_404(client):
    made = (await create(client)).json()
    url = f"{BASE}/{made['id']}"
    assert (await client.delete(url, headers=h("olga"))).status_code == 204
    assert (await client.get(url, headers=h("olga"))).status_code == 404
    async with client.db_state.session_factory() as s:
        row = (
            (await s.execute(select(Collection).execution_options(include_deleted=True)))
            .scalars()
            .one()
        )
        assert row.is_deleted


# --- visibility ---------------------------------------------------------------


async def test_visibility_beyond_private_needs_publish(client):
    made = (await create(client)).json()
    url = f"{BASE}/{made['id']}/visibility"
    for target in ("internal", "public"):
        r = await client.put(url, json={"visibility": target}, headers=h("olga", WRITER))
        assert r.status_code == 403, target
    r = await client.put(url, json={"visibility": "public"}, headers=h("olga", PUBLISHER))
    assert r.status_code == 200
    assert r.json()["visibility"] == "public"
    # going back to private needs nothing
    r = await client.put(url, json={"visibility": "private"}, headers=h("olga", WRITER))
    assert r.json()["visibility"] == "private"


async def test_create_as_public_needs_publish_too(client):
    assert (await create(client, visibility="public")).status_code == 403
    r = await create(client, perms=PUBLISHER, visibility="internal")
    assert r.status_code == 201
    assert r.json()["visibility"] == "internal"


async def test_only_owner_or_manager_changes_visibility(client):
    made = (await create(client)).json()
    async with client.db_state.session_factory() as s:
        coll = (await s.execute(select(Collection))).scalars().one()
        s.add(share(coll, "eddie", "edit"))
        await s.commit()
    url = f"{BASE}/{made['id']}/visibility"
    body = {"visibility": "internal"}
    assert (await client.put(url, json=body, headers=h("eddie", PUBLISHER))).status_code == 403
    assert (await client.put(url, json=body, headers=h("sam", PUBLISHER))).status_code == 404
    mgr = h("max", (*PUBLISHER, "images.manage"))
    assert (await client.put(url, json=body, headers=mgr)).status_code == 200


async def test_unknown_visibility_is_422(client):
    made = (await create(client)).json()
    r = await client.put(
        f"{BASE}/{made['id']}/visibility", json={"visibility": "x"}, headers=h("olga")
    )
    assert r.status_code == 422


# --- events -------------------------------------------------------------------


@pytest.fixture
def seen(client):
    events: list = []

    async def record(event):
        events.append(event)

    bus = client.app.state.sm.event_bus
    bus.subscribe(CollectionVisibilityChanged, record)
    bus.subscribe(CollectionDeleted, record)
    return events


async def test_events_fire_after_commit_with_the_tenant(client, seen):
    made = (await create(client, perms=PUBLISHER)).json()
    assert seen == []

    visible_at_publish: list[bool] = []

    async def probe(event):
        # a separate session reads committed data only
        async with client.db_state.session_factory() as s:
            row = (await s.execute(select(Collection.visibility))).scalars().one()
        visible_at_publish.append(row == Visibility.PUBLIC)

    client.app.state.sm.event_bus.subscribe(CollectionVisibilityChanged, probe)
    url = f"{BASE}/{made['id']}"
    await client.put(
        f"{url}/visibility", json={"visibility": "public"}, headers=h("olga", PUBLISHER)
    )
    await client.put(
        f"{url}/visibility", json={"visibility": "public"}, headers=h("olga", PUBLISHER)
    )
    await client.delete(url, headers=h("olga"))

    assert [type(e).__name__ for e in seen] == ["CollectionVisibilityChanged", "CollectionDeleted"]
    changed = seen[0]
    assert (changed.before, changed.after, changed.tenant_id) == ("private", "public", "default")
    assert changed.collection_id == made["id"]
    assert visible_at_publish == [True]


async def test_no_event_when_the_request_fails(client, seen):
    made = (await create(client)).json()
    r = await client.put(
        f"{BASE}/{made['id']}/visibility", json={"visibility": "public"}, headers=h("olga", WRITER)
    )
    assert r.status_code == 403
    assert seen == []


MANAGER_ONLY = (*WRITER, "images.manage")


async def test_manage_alone_satisfies_publish(client):
    """The tenant bypass: ``images.manage`` publishes without ``images.publish``."""
    r = await create(client, who="max", perms=MANAGER_ONLY, visibility="public")
    assert r.status_code == 201, r.text
    made = (await create(client, who="max", perms=MANAGER_ONLY, name="Two")).json()
    r = await client.put(
        f"{BASE}/{made['id']}/visibility",
        json={"visibility": "internal"},
        headers=h("max", MANAGER_ONLY),
    )
    assert r.status_code == 200
    assert r.json()["visibility"] == "internal"


async def test_a_failure_after_emit_publishes_nothing(client, seen, monkeypatch):
    """The event is queued on the session; the request then fails and rolls back."""
    from sm_images.endpoints.api import collections as routes

    made = (await create(client, perms=PUBLISHER)).json()

    def boom(*_a, **_k):
        raise RuntimeError("after emit")

    monkeypatch.setattr(routes, "out", boom)
    with pytest.raises(RuntimeError):
        await client.put(
            f"{BASE}/{made['id']}/visibility",
            json={"visibility": "public"},
            headers=h("olga", PUBLISHER),
        )
    assert seen == []
    async with client.db_state.session_factory() as s:
        assert (
            await s.execute(select(Collection.visibility))
        ).scalars().one() == Visibility.PRIVATE
