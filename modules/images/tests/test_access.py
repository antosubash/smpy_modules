"""The collection access matrix over HTTP: visibility x caller, list and detail.

Routes are the test-only router of :mod:`tests.access_support`; the
expectations are spec §2: private is owner, shares and ``images.manage``;
internal adds every signed-in member, read-only; public adds anonymous. An
invisible collection is a 404 (never a 403), a visible one without the action
a 403.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.access_support import (
    ADMIN_BASE,
    ANON,
    EDITOR,
    MANAGER,
    OWNER,
    PUBLIC_BASE,
    STRANGER,
    VIEWER,
    headers,
    mount,
    seed_matrix,
)


@pytest_asyncio.fixture
async def matrix(client):
    mount(client.app)
    ids = await seed_matrix(client.db_state.session_factory)
    return client, ids


LIST_EXPECTED = {
    OWNER: ["int", "priv", "pub"],
    STRANGER: ["int", "pub"],  # the expired edit share counts for nothing
    VIEWER: ["int", "priv", "pub"],
    EDITOR: ["int", "priv", "pub"],
    MANAGER: ["int", "priv", "pub"],
    ANON: ["pub"],
}


@pytest.mark.parametrize("who", list(LIST_EXPECTED))
async def test_list_shows_exactly_what_the_caller_may_view(matrix, who):
    client, _ = matrix
    response = await client.get(ADMIN_BASE, headers=headers(who))
    assert response.status_code == 200
    # "gone" is trashed: not listed for anyone, owner and bypass included.
    assert response.json() == LIST_EXPECTED[who]


# (collection, caller) -> detail status; must agree with the list above.
DETAIL_EXPECTED = {
    "priv": {OWNER: 200, STRANGER: 404, VIEWER: 200, EDITOR: 200, MANAGER: 200, ANON: 404},
    "int": {OWNER: 200, STRANGER: 200, VIEWER: 200, EDITOR: 200, MANAGER: 200, ANON: 404},
    "pub": {OWNER: 200, STRANGER: 200, VIEWER: 200, EDITOR: 200, MANAGER: 200, ANON: 200},
    "gone": {OWNER: 404, STRANGER: 404, VIEWER: 404, EDITOR: 404, MANAGER: 404, ANON: 404},
}


@pytest.mark.parametrize(
    ("slug", "who"), [(s, w) for s, row in DETAIL_EXPECTED.items() for w in row]
)
async def test_detail_agrees_with_the_list(matrix, slug, who):
    client, ids = matrix
    response = await client.get(f"{ADMIN_BASE}/{ids[slug]}", headers=headers(who))
    assert response.status_code == DETAIL_EXPECTED[slug][who]
    if response.status_code == 200:
        assert response.json() == {"slug": slug}


EDIT_EXPECTED = {
    # A view share sees but cannot upload; an edit share can.
    "priv": {OWNER: 200, STRANGER: 404, VIEWER: 403, EDITOR: 200, MANAGER: 200, ANON: 404},
    # internal and public grant view only, never edit.
    "int": {OWNER: 200, STRANGER: 403, VIEWER: 403, EDITOR: 403, MANAGER: 200, ANON: 404},
    "pub": {OWNER: 200, STRANGER: 403, VIEWER: 403, EDITOR: 403, MANAGER: 200, ANON: 403},
}


@pytest.mark.parametrize(("slug", "who"), [(s, w) for s, row in EDIT_EXPECTED.items() for w in row])
async def test_upload_needs_edit(matrix, slug, who):
    client, ids = matrix
    response = await client.post(f"{ADMIN_BASE}/{ids[slug]}/images", headers=headers(who))
    assert response.status_code == EDIT_EXPECTED[slug][who]


OWNER_EXPECTED = {
    # An edit share still cannot delete: owner or images.manage only.
    "priv": {OWNER: 200, STRANGER: 404, VIEWER: 403, EDITOR: 403, MANAGER: 200, ANON: 404},
    "int": {OWNER: 200, STRANGER: 403, VIEWER: 403, EDITOR: 403, MANAGER: 200, ANON: 404},
    "pub": {OWNER: 200, STRANGER: 403, VIEWER: 403, EDITOR: 403, MANAGER: 200, ANON: 403},
}


@pytest.mark.parametrize(
    ("slug", "who"), [(s, w) for s, row in OWNER_EXPECTED.items() for w in row]
)
async def test_delete_is_owner_or_manage(matrix, slug, who):
    client, ids = matrix
    response = await client.delete(f"{ADMIN_BASE}/{ids[slug]}", headers=headers(who))
    assert response.status_code == OWNER_EXPECTED[slug][who]


async def test_malformed_and_unknown_ids_are_404(matrix):
    client, _ = matrix
    owner = headers(OWNER)
    assert (
        await client.get(f"{ADMIN_BASE}/00000000-0000-0000-0000-000000000000", headers=owner)
    ).status_code == 404
    assert (await client.get(f"{ADMIN_BASE}/not-a-uuid", headers=owner)).status_code == 422


@pytest.mark.parametrize(
    ("slug", "status"),
    [("pub", 200), ("int", 404), ("priv", 404), ("gone", 404), ("missing", 404)],
)
@pytest.mark.parametrize("who", [ANON, OWNER, MANAGER])
async def test_public_page_is_public_collections_only(matrix, slug, status, who):
    """Signed in or not, owner or bypass: the anonymous surface serves public only."""
    client, _ = matrix
    response = await client.get(f"{PUBLIC_BASE}/c/{slug}", headers=headers(who))
    assert response.status_code == status
