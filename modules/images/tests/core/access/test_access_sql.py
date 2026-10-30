"""The policy as SQL, without HTTP: collections, images, originals, registration.

``filter`` is the authority (``can`` is a fast path that may say no where
``filter`` says yes), so every action is checked against the statement it
builds, and ``can`` is checked never to say yes where ``filter`` says no.
"""

from __future__ import annotations

import pytest
from simple_module_core.resources import (
    ACTION_DELETE,
    ACTION_EDIT,
    ACTION_SHARE,
    ACTION_VIEW,
    ResourcePolicy,
    ResourceTypeRegistry,
)
from sm_images.core.access import (
    COLLECTION_RESOURCE,
    POLICY,
    can_view_original,
    visible_collections,
    visible_images,
)
from sm_images.models import Collection, Visibility
from sm_images.module import ImagesModule

from tests.support.access import (
    ANON,
    CALLERS,
    EDITOR,
    MANAGER,
    OWNER,
    STRANGER,
    VIEWER,
    collection,
    image,
    principal,
    seed_matrix,
)

ALL = {"priv", "int", "pub"}
EXPECTED = {
    ACTION_VIEW: {
        OWNER: ALL,
        STRANGER: {"int", "pub"},
        VIEWER: ALL,
        EDITOR: ALL,
        MANAGER: ALL,
        ANON: {"pub"},
    },
    ACTION_EDIT: {
        OWNER: ALL,
        STRANGER: set(),
        VIEWER: set(),
        EDITOR: {"priv"},
        MANAGER: ALL,
        ANON: set(),
    },
    # Shares never reach delete or share, whatever their role.
    ACTION_DELETE: {
        OWNER: ALL,
        STRANGER: set(),
        VIEWER: set(),
        EDITOR: set(),
        MANAGER: ALL,
        ANON: set(),
    },
    ACTION_SHARE: {
        OWNER: ALL,
        STRANGER: set(),
        VIEWER: set(),
        EDITOR: set(),
        MANAGER: ALL,
        ANON: set(),
    },
}


@pytest.mark.parametrize("action", list(EXPECTED))
@pytest.mark.parametrize("who", CALLERS)
async def test_filter_matrix(db_state, action, who):
    await seed_matrix(db_state.session_factory)
    async with db_state.session_factory() as s:
        rows = (await s.execute(visible_collections(principal(who), action))).scalars().all()
        assert {r.slug for r in rows} == EXPECTED[action][who]
        # ``can`` is only ever stricter than ``filter``.
        everything = (
            await s.execute(visible_collections(principal(MANAGER), ACTION_VIEW))
        ).scalars()
        for row in everything:
            if POLICY.can(principal(who), action, row):
                assert row.slug in EXPECTED[action][who]


async def test_internal_needs_a_signed_in_principal():
    internal = collection("int", Visibility.INTERNAL)
    assert POLICY.can(principal(STRANGER), ACTION_VIEW, internal)
    assert not POLICY.can(principal(ANON), ACTION_VIEW, internal)
    assert not POLICY.can(principal(STRANGER), ACTION_EDIT, internal)
    assert not POLICY.can(principal(STRANGER), ACTION_EDIT, collection("p", Visibility.PUBLIC))


async def test_visible_images_follow_their_collection(db_state):
    ids = await seed_matrix(db_state.session_factory)
    async with db_state.session_factory() as s:
        colls = {
            c.slug: c
            for c in (
                await s.execute(visible_collections(principal(MANAGER), ACTION_VIEW))
            ).scalars()
        }
        s.add_all([image(colls[slug], f"{slug}.jpg") for slug in ("priv", "int", "pub")])
        s.add(image(colls["pub"], "trashed.jpg", is_deleted=True))
        gone = await s.get(Collection, ids["gone"], execution_options={"include_deleted": True})
        s.add(image(gone, "in-trashed-collection.jpg"))
        await s.commit()

    async def names(who, action=ACTION_VIEW):
        async with db_state.session_factory() as s:
            return {
                i.filename
                for i in (await s.execute(visible_images(principal(who), action))).scalars()
            }

    assert await names(OWNER) == {"priv.jpg", "int.jpg", "pub.jpg"}
    assert await names(MANAGER) == {"priv.jpg", "int.jpg", "pub.jpg"}
    assert await names(STRANGER) == {"int.jpg", "pub.jpg"}
    assert await names(VIEWER) == {"priv.jpg", "int.jpg", "pub.jpg"}
    assert await names(ANON) == {"pub.jpg"}
    assert await names(EDITOR, ACTION_EDIT) == {"priv.jpg"}
    assert await names(VIEWER, ACTION_EDIT) == set()
    assert await names(STRANGER, ACTION_DELETE) == set()

    # A trash view of images (include_deleted) still never reaches into a
    # trashed collection: that exclusion is the statement's own, not the mixin's.
    async with db_state.session_factory() as s:
        trash = visible_images(principal(MANAGER), ACTION_VIEW).execution_options(
            include_deleted=True
        )
        found = {i.filename for i in (await s.execute(trash)).scalars()}
    assert found == {"priv.jpg", "int.jpg", "pub.jpg", "trashed.jpg"}


def test_original_needs_owner_or_the_originals_permission():
    coll = collection("c", Visibility.INTERNAL)
    blurred = image(coll, "b.jpg", display_key="k/b.display.jpg")
    plain = image(coll, "p.jpg")
    for who in (STRANGER, VIEWER, EDITOR, MANAGER):
        assert can_view_original(principal(who), plain, coll)
        assert not can_view_original(principal(who), blurred, coll)
    assert can_view_original(principal(OWNER), blurred, coll)
    holder = principal(STRANGER)
    holder = type(holder)(user_id=holder.user_id, permissions=frozenset({"images.originals.view"}))
    assert can_view_original(holder, blurred, coll)
    # An image paired with the wrong collection is never trusted.
    other = collection("o", Visibility.PUBLIC)
    assert not can_view_original(principal(OWNER), plain, other)


def test_the_resource_type_is_registered_with_the_same_policy():
    registry = ResourceTypeRegistry()
    ImagesModule().register_resource_types(registry)
    registered = registry.get(COLLECTION_RESOURCE)
    assert COLLECTION_RESOURCE == "images.collection"
    assert registered is not None
    assert registered.policy is POLICY
    assert isinstance(POLICY, ResourcePolicy)
    assert set(registered.shareable_actions) == {ACTION_VIEW, ACTION_EDIT}


def test_depends_on_names_the_real_modules():
    assert {"Settings", "Sharing", "FileStorage", "BackgroundTasks"} <= set(
        ImagesModule.meta.depends_on
    )
