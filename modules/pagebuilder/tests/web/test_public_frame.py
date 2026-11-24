"""Frame reuse must not add reads or query the layout-less 404 paths."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pagebuilder.content import site_nav
from pagebuilder.content.layout_service import LayoutService
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.web.endpoints.public_not_found import render_not_found

from tests.web.test_public_viewer import _create_published

pytestmark = pytest.mark.asyncio


async def test_viewer_reuses_its_etag_layout_and_navigation(authed_client):
    await _create_published(authed_client)
    with (
        patch.object(LayoutService, "get", autospec=True, side_effect=LayoutService.get) as layout,
        patch.object(site_nav, "site_nav", wraps=site_nav.site_nav) as nav,
    ):
        response = await authed_client.get(
            "/p/hello",
            headers={"X-Inertia": "true", "X-Inertia-Version": "1.0", "X-Test-Anonymous": "1"},
        )
    assert response.status_code == 200
    assert response.headers["ETag"]
    layout.assert_awaited_once()
    nav.assert_awaited_once()


@pytest.mark.parametrize("json_only", [False, True])
async def test_not_found_skips_frame_reads_without_a_tenant_or_for_json(json_only):
    request = Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": (
                [(b"accept", b"application/json")] if json_only else [(b"x-inertia", b"true")]
            ),
        }
    )
    inertia = AsyncMock()
    inertia.render.return_value = JSONResponse({})
    with (
        patch.object(LayoutService, "get", side_effect=AssertionError("read layout")),
        patch.object(site_nav, "site_nav", side_effect=AssertionError("read navigation")),
    ):
        response = await render_not_found(
            request, inertia, PagebuilderSettings(), locale="de", db=object() if json_only else None
        )
    assert response.status_code == 404
    if json_only:
        inertia.render.assert_not_awaited()
        assert response.body == b'{"detail":"Page not found"}'
    else:
        props = inertia.render.call_args.args[1]
        assert props["layout_header"] is props["layout_footer"] is props["site_nav"] is None
        assert props["copy"]["skip_to_content"] == "Zum Inhalt springen"
