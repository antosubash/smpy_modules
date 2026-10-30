"""A page's nav flags and meta title: defaults and round trip through the API.

Moved out of ``test_redirects`` (#133), where they had landed for no reason
but that file having room.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

API = "/api/pagebuilder/pages"


class TestNavAndSeoFields:
    async def test_nav_flags_default_to_off(self, authed_client: AsyncClient) -> None:
        """Nothing was in the nav before the column existed."""
        page = (
            await authed_client.post(
                API, json={"title": "N", "slug": "nav", "draft_data": {"content": []}}
            )
        ).json()

        assert page["show_in_header_nav"] is False
        assert page["show_in_footer"] is False

    async def test_meta_title_defaults_to_null_meaning_use_the_title(
        self, authed_client: AsyncClient
    ) -> None:
        page = (
            await authed_client.post(
                API, json={"title": "T", "slug": "meta", "draft_data": {"content": []}}
            )
        ).json()

        assert page["meta_title"] is None

    async def test_they_round_trip_through_an_update(self, authed_client: AsyncClient) -> None:
        page = (
            await authed_client.post(
                API, json={"title": "R", "slug": "round", "draft_data": {"content": []}}
            )
        ).json()

        await authed_client.put(
            f"{API}/{page['id']}",
            json={
                "meta_title": "Round — Acme Lab",
                "show_in_header_nav": True,
                "show_in_footer": True,
            },
        )

        back = (await authed_client.get(f"{API}/{page['id']}")).json()
        assert back["meta_title"] == "Round — Acme Lab"
        assert back["show_in_header_nav"] is True
        assert back["show_in_footer"] is True
