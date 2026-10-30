"""The contract reads name a tenant and a principal, and honour both."""

from __future__ import annotations

import uuid

import pytest
from simple_module_db.listeners import TenantIsolationError
from sm_images import contracts
from sm_images.models import Image, Visibility
from sm_images.storage.intents import use_session_factory
from sm_images.tenancy import tenant_scope

from tests.support.access import (
    ANON,
    EDITOR,
    MANAGER,
    OWNER,
    STRANGER,
    VIEWER,
    collection,
    principal,
    share,
)

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def seeded(db_state):
    """acme: priv (shared with vic), int, pub; globex: g-pub."""
    use_session_factory(db_state.session_factory)
    with tenant_scope("acme"):
        priv = collection("priv", Visibility.PRIVATE)
        async with db_state.session_factory() as s:
            s.add_all(
                [priv, collection("int", Visibility.INTERNAL), collection("pub", Visibility.PUBLIC)]
            )
            await s.flush()
            s.add(share(priv, VIEWER, "view"))
            await s.commit()
        ids = {"priv": priv.id}
    with tenant_scope("globex"):
        g = collection("g-pub", Visibility.PUBLIC)
        async with db_state.session_factory() as s:
            s.add(g)
            await s.commit()
        ids["g"] = g.id
    return ids


async def slugs(tenant, who, **kw):
    page = await contracts.list_collections(tenant, principal(who), **kw)
    return sorted(i.slug for i in page.items)


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        (OWNER, ["int", "priv", "pub"]),
        (VIEWER, ["int", "priv", "pub"]),
        (MANAGER, ["int", "priv", "pub"]),
        (STRANGER, ["int", "pub"]),
        (EDITOR, ["int", "pub"]),  # no share was granted to eddie here
        (ANON, ["pub"]),
    ],
)
async def test_list_is_policy_filtered(seeded, who, expected):
    assert await slugs("acme", who) == expected


async def test_list_is_tenant_filtered(seeded):
    assert await slugs("globex", OWNER) == ["g-pub"]
    assert await slugs("nobody", MANAGER) == []


async def test_get_is_policy_and_tenant_filtered(seeded):
    priv, g = seeded["priv"], seeded["g"]
    assert (await contracts.get_collection("acme", priv, principal(OWNER))).slug == "priv"
    assert (await contracts.get_collection("acme", priv, principal(VIEWER))).slug == "priv"
    assert await contracts.get_collection("acme", priv, principal(STRANGER)) is None
    assert await contracts.get_collection("acme", priv, principal(ANON)) is None
    assert await contracts.get_collection("globex", priv, principal(MANAGER)) is None
    assert await contracts.get_collection("acme", g, principal(MANAGER)) is None
    assert await contracts.get_collection("acme", uuid.uuid4(), principal(MANAGER)) is None


async def test_filters_apply_to_the_contract_too(seeded):
    assert await slugs("acme", VIEWER, filter="shared") == ["priv"]
    assert await slugs("acme", OWNER, filter="owned") == ["int", "priv", "pub"]
    assert await slugs("acme", OWNER, filter="internal") == ["int"]


async def test_pages_follow_the_cursor(seeded):
    first = await contracts.list_collections("acme", principal(OWNER), limit=2)
    assert len(first.items) == 2 and first.total == 3 and first.next_cursor
    rest = await contracts.list_collections(
        "acme", principal(OWNER), limit=2, cursor=first.next_cursor
    )
    assert len(rest.items) == 1 and rest.total is None and rest.next_cursor is None


async def test_the_callers_session_is_used_when_given(seeded, db_state):
    async with db_state.session_factory() as s:
        page = await contracts.list_collections("acme", principal(OWNER), db=s)
        assert len(page.items) == 3
        # the caller's session is left open for the caller to finish
        assert s.is_active


async def test_a_different_tenant_than_the_one_bound_is_refused(seeded):
    with tenant_scope("acme"), pytest.raises(TenantIsolationError):
        await contracts.list_collections("globex", principal(OWNER))


async def test_a_bad_tenant_id_is_refused(seeded):
    with pytest.raises(ValueError):
        await contracts.list_collections("", principal(OWNER))


async def test_the_tenant_is_unbound_again_afterwards(seeded):
    from simple_module_db.listeners import current_tenant_id

    await contracts.list_collections("acme", principal(OWNER))
    assert current_tenant_id.get() is None


def test_rendition_url_versions_by_the_renditions_bytes():
    from sm_images.models import Rendition
    from sm_images.serving import cache

    img = Image(
        id=uuid.UUID(int=7),
        collection_id=uuid.uuid4(),
        storage_key="k",
        filename="f",
        content_type="image/jpeg",
        size_bytes=1,
        display_generation=3,
    )
    rend = Rendition(
        image_id=img.id, size="400", storage_key="k/r/400", width=1, height=1, source_generation=3
    )
    url = contracts.rendition_url(img, rend)
    assert url == f"/api/images/images/{img.id}/r/400?v={cache.version(3, 'k/r/400')}"
