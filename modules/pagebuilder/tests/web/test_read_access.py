"""The admin reads need a pagebuilder permission (#346).

Signing in is not enough: on a host with self-registration or customer
accounts, every account would read every draft, its revision history, the
unpublished site layout and the whole media library. Any one of edit, publish
or approve opens them; a signed-in user holding none gets 403 on every read and
every screen, and a signed-out one still gets the 401 it always got.
"""

from __future__ import annotations

import pytest
from pagebuilder.core.permissions import PERM_APPROVE, PERM_EDIT, PERM_PUBLISH
from simple_module_hosting.permissions import PERMISSION_DENIED_PREFIX

from tests.support.app import _build_app, _client_for, _regrant
from tests.support.media_bytes import PNG

pytestmark = pytest.mark.asyncio

_ROLE = "someone"
_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}

# Ids that need not exist: the gate answers before the endpoint looks.
API_READS = [
    "/api/pagebuilder/pages",
    "/api/pagebuilder/pages/templates",
    "/api/pagebuilder/pages/1",
    "/api/pagebuilder/locales",
    "/api/pagebuilder/pages/1/revisions",
    "/api/pagebuilder/pages/1/revisions/1",
    "/api/pagebuilder/pages/1/revisions/1/diff/2",
    "/api/pagebuilder/layout",
    "/api/pagebuilder/layout/revisions",
    "/api/pagebuilder/layout/revisions/1",
    "/api/pagebuilder/uploads",
    "/api/pagebuilder/uploads/1",
]
VIEWS = [
    "/pagebuilder/",
    "/pagebuilder/new",
    "/pagebuilder/1/edit",
    "/pagebuilder/1/preview",
    "/pagebuilder/layout",
    "/pagebuilder/media",
    "/pagebuilder/media/1",
]


async def _client(tmp_path, grants: list[str]):
    """A signed-in client whose one role holds *grants*, after seeding as an editor.

    The page and the asset are created under ``pagebuilder.edit``, which is
    then replaced by *grants*, so the reads below have something real to find.
    """
    app, cleanup = await _build_app(
        tmp_path,
        requires_auth=True,
        csrf_protect=False,
        inject_user=True,
        user_roles=(_ROLE,),
        role_map={_ROLE: [PERM_EDIT]},
    )
    try:
        async with _client_for(app) as client:
            page = await client.post(
                "/api/pagebuilder/pages",
                json={"title": "Draft", "slug": "draft", "draft_data": {"content": []}},
            )
            assert page.status_code == 201, page.text
            asset = await client.post(
                "/api/pagebuilder/uploads", files={"file": ("a.png", PNG, "image/png")}
            )
            assert asset.status_code == 201, asset.text
            _regrant(app, _ROLE, grants)
            yield client, page.json()["id"], asset.json()["id"]
    finally:
        await cleanup()


@pytest.mark.parametrize("grants", [[], ["news.edit"]])
async def test_a_user_without_a_pagebuilder_permission_reads_nothing(tmp_path, grants):
    async for client, _page, _asset in _client(tmp_path, grants):
        for path in API_READS:
            response = await client.get(path)
            assert response.status_code == 403, path
            assert response.json()["detail"] == f"{PERMISSION_DENIED_PREFIX}{PERM_EDIT}", path
        for path in VIEWS:
            response = await client.get(path, headers=_INERTIA)
            assert response.status_code == 403, path
            assert "Draft" not in response.text, path


@pytest.mark.parametrize("grant", [PERM_EDIT, PERM_PUBLISH, PERM_APPROVE])
async def test_any_one_pagebuilder_permission_opens_the_reads(tmp_path, grant):
    async for client, page_id, asset_id in _client(tmp_path, [grant]):
        reads = [
            "/api/pagebuilder/pages",
            "/api/pagebuilder/pages/templates",
            f"/api/pagebuilder/pages/{page_id}",
            "/api/pagebuilder/locales",
            f"/api/pagebuilder/pages/{page_id}/revisions",
            "/api/pagebuilder/layout",
            "/api/pagebuilder/layout/revisions",
            "/api/pagebuilder/uploads",
        ]
        for path in reads:
            response = await client.get(path)
            assert response.status_code == 200, (path, response.text)
        views = [
            "/pagebuilder/",
            f"/pagebuilder/{page_id}/edit",
            f"/pagebuilder/{page_id}/preview",
            "/pagebuilder/layout",
            "/pagebuilder/media",
            f"/pagebuilder/media/{asset_id}",
        ]
        for path in views:
            response = await client.get(path, headers=_INERTIA)
            assert response.status_code == 200, (path, response.text)


async def test_the_asset_detail_still_needs_edit(tmp_path):
    """``GET /uploads/{id}`` was already behind ``pagebuilder.edit``: the gate never widens."""
    async for client, _page, asset_id in _client(tmp_path, [PERM_APPROVE]):
        response = await client.get(f"/api/pagebuilder/uploads/{asset_id}")
        assert response.status_code == 403


async def test_a_signed_out_request_still_gets_401(client):
    for path in API_READS:
        assert (await client.get(path)).status_code == 401, path
