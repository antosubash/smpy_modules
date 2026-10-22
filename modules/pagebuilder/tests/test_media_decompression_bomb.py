"""An image with too many pixels is refused, not a 500 (#221).

Pillow guards decoding with ``Image.MAX_IMAGE_PIXELS`` (about 89 megapixels):
above twice the limit ``Image.open`` raises ``DecompressionBombError``, between
one and two times it only warns. Both are refused with the same 413 and its
``image_too_many_pixels`` code, and the file is not kept. The tests lower the
limit so a tiny PNG stands in for a 200-megapixel one.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import AsyncClient
from PIL import Image

API = "/api/pagebuilder/uploads"

pytestmark = pytest.mark.asyncio


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buf, format="PNG")
    return buf.getvalue()


def _stored_files(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "media").rglob("*") if p.is_file()]


async def _upload(client: AsyncClient, content: bytes):  # type: ignore[no-untyped-def]
    return await client.post(API, files={"file": ("huge.png", content, "image/png")})


@pytest.mark.parametrize(
    ("side", "case"),
    [(20, "over twice the limit: DecompressionBombError"), (12, "1x-2x: the warning")],
)
async def test_too_many_pixels_is_refused_and_not_stored(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch, side: int, case: str
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    response = await _upload(authed_client, _png(side, side))

    assert response.status_code == 413, (case, response.text)
    assert response.json()["detail"]["code"] == "image_too_many_pixels"
    assert _stored_files(tmp_path) == []
    listed = await authed_client.get(API)
    assert listed.json()["items"] == []


async def test_an_image_at_the_limit_still_uploads(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    response = await _upload(authed_client, _png(10, 10))

    assert response.status_code == 201, response.text
    assert response.json()["width"] == 10
    assert len(_stored_files(tmp_path)) == 1


async def test_a_disabled_limit_accepts_any_size(
    authed_client: AsyncClient, monkeypatch
) -> None:
    # A host may switch Pillow's guard off (``MAX_IMAGE_PIXELS = None``).
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)

    response = await _upload(authed_client, _png(20, 20))

    assert response.status_code == 201, response.text
