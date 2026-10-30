"""The upload routes' body ceiling, enforced by the host's own middleware.

Through the full app (``create_app``), not the harness: what is under test is
that the framework's ``BodyLimitMiddleware`` consults images'
``register_body_limits`` - an upload route admits a body above the global
``max_request_body_bytes`` up to ``upload_body_max_bytes`` (plus multipart
framing), and refuses one above it before any handler or auth runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from simple_module_hosting import Settings, app_builder, create_app
from sm_images.core import constants
from sm_images.core.settings import ImagesSettings

MIB = 1024 * 1024
UPLOAD = "/api/images/collections/00000000-0000-0000-0000-000000000001/images"
ROUTES = [UPLOAD, f"{UPLOAD}/base64", "/api/images/uploads/token/complete"]


REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def host_app():
    """``create_app`` resolves the host's templates from the project root it
    computed at import (the working directory then). Run from ``modules/images/``
    (CI, the Makefile) that is the wrong directory, so it is pointed at the repo."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(app_builder, "_PROJECT_ROOT", REPO)
        yield create_app(Settings())


async def _post(app, path: str, declared: int):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            path,
            content=b"x" * 16,
            headers={
                "Content-Type": "application/octet-stream",
                "Accept": "application/json",
                "Content-Length": str(declared),
            },
        )


@pytest.mark.parametrize("path", ROUTES)
async def test_body_limit_via_host_middleware(host_app, path):
    ceiling = ImagesSettings().upload_body_max_bytes + constants.MULTIPART_OVERHEAD_BYTES
    global_max = Settings().max_request_body_bytes
    assert global_max < 50 * MIB < ceiling  # the override is what admits this body

    over = await _post(host_app, path, ceiling + 1)
    assert over.status_code == 413, over.text

    under = await _post(host_app, path, 50 * MIB)
    assert under.status_code != 413, under.text  # past the guard: auth refuses it


async def test_a_non_upload_route_keeps_the_global_limit(host_app):
    got = await _post(host_app, "/api/images/collections", 50 * MIB)
    assert got.status_code == 413
