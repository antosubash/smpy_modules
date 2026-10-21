"""A valid CSRF token is not a permission (#111).

``RequiresCsrf`` runs before the permission check, so a write without a token
is refused before the permission check is reached — which is why the
records-permissions e2e spec's 403 no longer proves the permission gate. These
tests send the session's *real* token, taken from the records screen, and
assert the refusal is the permission check's, not the CSRF one.
"""

from __future__ import annotations

import pytest
from simple_module_hosting.csrf import CSRF_HEADER
from simple_module_hosting.permissions import PERMISSION_DENIED_PREFIX

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, roles
from tests.csrf_support import TYPES, _create_type, _token, _type_body

pytestmark = pytest.mark.asyncio


def _assert_permission_refusal(response) -> None:
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert "CSRF" not in detail
    assert detail.startswith(PERMISSION_DENIED_PREFIX), detail


@pytest.mark.parametrize("role", [ROLE_VIEWER, ROLE_EDITOR])
async def test_a_valid_token_without_manage_cannot_create_a_type(session_client, role) -> None:
    token = await _token(session_client)
    response = await session_client.post(
        TYPES, json=_type_body("forbidden"), headers={**roles(role), CSRF_HEADER: token}
    )
    _assert_permission_refusal(response)
    listed = await session_client.get(TYPES, headers=roles(ADMIN))
    assert [t["key"] for t in listed.json()["items"]] == []


async def test_a_valid_token_without_edit_cannot_write_records(session_client) -> None:
    token = await _token(session_client)
    await _create_type(session_client, token, "product")
    armed_viewer = {**roles(ROLE_VIEWER), CSRF_HEADER: token}
    base = f"{TYPES}/product/records"

    created = await session_client.post(base, json={"data": {"name": "x"}}, headers=armed_viewer)
    _assert_permission_refusal(created)
    emptied = await session_client.post(f"{base}/trash/empty", json={}, headers=armed_viewer)
    _assert_permission_refusal(emptied)

    listed = await session_client.get(base, headers=roles(ADMIN))
    assert listed.json()["items"] == []
