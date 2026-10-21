"""The admin API refuses a write without the session's CSRF token (#111).

Records exposes destructive writes — bulk purge, emptying the trash, schema
changes, imports — and used to rely on the session cookie's ``SameSite=Lax``
alone, which does not separate the console from an organisation's public site
on a multi-tenant host: the two are same-site.

The session-backed client and the token helpers are in ``csrf_support``;
``test_csrf_permissions`` covers what a valid token does *not* grant.
"""

from __future__ import annotations

import pytest
from simple_module_hosting.csrf import CSRF_HEADER
from sm_records.constants import ROUTE_PREFIX_API

from tests.csrf_support import AS_ADMIN, TYPES, _create_type, _token, _type_body

pytestmark = pytest.mark.asyncio


async def test_a_write_without_the_token_is_refused_and_writes_nothing(session_client) -> None:
    await _token(session_client)  # the session has a token; the request omits it
    response = await session_client.post(TYPES, json=_type_body("forged"), headers=AS_ADMIN)
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    listed = await session_client.get(TYPES, headers=AS_ADMIN)
    assert [t["key"] for t in listed.json()["items"]] == []


async def test_a_wrong_token_is_refused(session_client) -> None:
    await _token(session_client)
    response = await session_client.post(
        TYPES, json=_type_body("wrong"), headers={**AS_ADMIN, CSRF_HEADER: "not-the-token"}
    )
    assert response.status_code == 403


async def test_a_write_before_any_view_is_refused(session_client) -> None:
    response = await session_client.post(
        TYPES, json=_type_body("early"), headers={**AS_ADMIN, CSRF_HEADER: ""}
    )
    assert response.status_code == 403


async def test_put_and_delete_are_checked_and_pass_with_the_token(session_client) -> None:
    token = await _token(session_client)
    created = await _create_type(session_client, token, "product")
    url = f"{TYPES}/product"
    edit = {"expected_version": created["version"], "label": "Forged"}

    assert (await session_client.put(url, json=edit, headers=AS_ADMIN)).status_code == 403
    assert (await session_client.delete(url, headers=AS_ADMIN)).status_code == 403
    still = await session_client.get(url, headers=AS_ADMIN)
    assert still.json()["label"] == "Product"

    armed = {**AS_ADMIN, CSRF_HEADER: token}
    renamed = await session_client.put(url, json={**edit, "label": "Products"}, headers=armed)
    assert renamed.status_code == 200, renamed.text
    deleted = await session_client.delete(url, params={"confirm_record_count": 0}, headers=armed)
    assert deleted.status_code in (200, 204), deleted.text


@pytest.mark.parametrize(
    "path",
    [
        "/types/product/records/bulk",
        "/types/product/records/trash/empty",
        "/types/product/records/import",
    ],
)
async def test_the_destructive_writes_are_refused(session_client, path) -> None:
    """The writes #111 names — bulk purge, emptying the trash, imports."""
    token = await _token(session_client)
    await _create_type(session_client, token, "product")
    response = await session_client.post(f"{ROUTE_PREFIX_API}{path}", json={}, headers=AS_ADMIN)
    assert response.status_code == 403


async def test_patch_is_checked_too(session_client) -> None:
    """No records route takes PATCH today; one added under the router would be checked.

    Mounted with the API router's own dependency list, which is what every
    route included from it inherits.
    """
    from sm_records.endpoints.api import router

    async def _patch() -> dict[str, bool]:
        return {"patched": True}

    path = f"{ROUTE_PREFIX_API}/__patch__"
    session_client.app.add_api_route(  # type: ignore[attr-defined]
        path, _patch, methods=["PATCH"], dependencies=router.dependencies
    )
    token = await _token(session_client)
    assert (await session_client.patch(path, headers=AS_ADMIN)).status_code == 403
    allowed = await session_client.patch(path, headers={**AS_ADMIN, CSRF_HEADER: token})
    assert allowed.status_code == 200, allowed.text


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_safe_methods_need_no_token(session_client, method) -> None:
    response = await session_client.request(method, TYPES, headers=AS_ADMIN)
    assert response.status_code != 403
