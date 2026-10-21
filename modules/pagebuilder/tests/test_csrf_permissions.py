"""A valid CSRF token is not a permission (#126).

``RequiresCsrf`` runs before the permission check, so a write without a token
is refused before the permission check is reached. This session sends its
*real* token, taken from a pagebuilder screen it may see, and the refusal it
gets must be the permission check's, not the CSRF one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from conftest import _client_fixture
from httpx import AsyncClient
from pagebuilder.permissions import PERM_EDIT, PERM_PUBLISH, ROLE_EDITOR
from simple_module_hosting.csrf import CSRF_HEADER
from simple_module_hosting.permissions import PERMISSION_DENIED_PREFIX
from test_csrf import PAGES, create_page, token_from_console

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def editor(tmp_path) -> AsyncIterator[AsyncClient]:
    """A CSRF-checked session holding ``pagebuilder.edit`` and nothing else."""
    async for client in _client_fixture(
        tmp_path,
        requires_auth=True,
        csrf_protect=True,
        inject_user=True,
        user_roles=(ROLE_EDITOR,),
        role_map={ROLE_EDITOR: [PERM_EDIT]},
    ):
        yield client


async def test_an_editor_with_a_valid_token_cannot_publish(editor) -> None:
    token = await token_from_console(editor)
    page = await create_page(editor, token, "draft")  # edit is enough for this
    response = await editor.post(f"{PAGES}/{page['id']}/publish", headers={CSRF_HEADER: token})
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert "CSRF" not in detail
    assert detail == f"{PERMISSION_DENIED_PREFIX}{PERM_PUBLISH}"
    # Nothing was published.
    after = await editor.get(f"{PAGES}/{page['id']}")
    assert after.json()["status"] == page["status"]
