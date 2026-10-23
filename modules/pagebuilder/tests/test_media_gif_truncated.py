"""A GIF cut short inside its second frame is not a 500 (#221).

Pillow's ``is_animated`` reads the start of frame two, and raises
``IndexError`` or ``struct.error`` when that frame is cut off: a bare ``!``
at the end of the file, or an image descriptor without its flags byte. The
upload completes like any other image Pillow cannot process fully (no
thumbnails), unless the cut-off descriptor already claims too many pixels,
which Pillow checks from its first eight bytes and so does the walk.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import AsyncClient
from pagebuilder.media_gif import gif_canvas_size
from PIL import Image

API = "/api/pagebuilder/uploads"

pytestmark = pytest.mark.asyncio


def _first_frame_only() -> bytes:
    buf = io.BytesIO()
    Image.new("P", (10, 10), 0).save(buf, format="GIF")
    return buf.getvalue()[:-1]  # drop the trailer


def _descriptor_without_flags(side: int) -> bytes:
    size = side.to_bytes(2, "little")
    return b"," + b"\x00\x00\x00\x00" + size + size


def _stored_files(tmp_path: Path) -> list[Path]:
    return [p for p in (tmp_path / "media").rglob("*") if p.is_file()]


async def _upload(client: AsyncClient, content: bytes):  # type: ignore[no-untyped-def]
    return await client.post(API, files={"file": ("cut.gif", content, "image/gif")})


@pytest.mark.parametrize(
    "tail",
    [
        pytest.param(b"!", id="bare-extension-introducer"),
        pytest.param(_descriptor_without_flags(5), id="descriptor-cut-to-8-bytes"),
    ],
)
async def test_a_gif_cut_short_in_frame_two_still_uploads(
    authed_client: AsyncClient, tmp_path: Path, tail: bytes
) -> None:
    response = await _upload(authed_client, _first_frame_only() + tail)

    assert response.status_code == 201, response.text
    assert response.json()["variants"] in ({}, None)
    assert len(_stored_files(tmp_path)) == 1


async def test_a_cut_off_descriptor_over_the_limit_is_refused(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    content = _first_frame_only() + _descriptor_without_flags(20)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    # Pillow grows the canvas from those eight bytes, bomb check included,
    # before it fails on the missing flags byte.
    with Image.open(io.BytesIO(content)) as image, pytest.raises(Image.DecompressionBombError):
        image.seek(1)

    response = await _upload(authed_client, content)

    assert response.status_code == 413, response.text
    assert _stored_files(tmp_path) == []


async def test_the_walk_grows_from_an_eight_byte_descriptor(tmp_path: Path) -> None:
    path = tmp_path / "cut.gif"
    path.write_bytes(_first_frame_only() + _descriptor_without_flags(0x67))
    assert gif_canvas_size(path) == (0x67, 0x67)
