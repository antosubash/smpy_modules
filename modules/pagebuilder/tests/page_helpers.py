"""Page-creating helpers shared across tests.

A plain module rather than a conftest addition: ``conftest.py`` sits exactly on
the repo's 300-line cap, and ``tests`` is on ``pythonpath`` (see the module's
``[tool.pytest.ini_options]``), so ``from page_helpers import create_draft``
works from any test file.
"""

from __future__ import annotations

from httpx import AsyncClient


async def create_draft(
    client: AsyncClient,
    *,
    slug: str = "post",
    title: str = "Draft",
    draft_data: dict | None = None,
) -> dict:
    """POST a fresh draft page and return the API body."""
    response = await client.post(
        "/api/pagebuilder/pages",
        json={
            "title": title,
            "slug": slug,
            "draft_data": draft_data
            if draft_data is not None
            else {"content": ["hello"]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
