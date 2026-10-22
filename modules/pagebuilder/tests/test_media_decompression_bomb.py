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
from pagebuilder.media_gif import gif_canvas_size
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


async def test_a_disabled_limit_accepts_any_size(authed_client: AsyncClient, monkeypatch) -> None:
    # A host may switch Pillow's guard off (``MAX_IMAGE_PIXELS = None``).
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", None)

    response = await _upload(authed_client, _png(20, 20))

    assert response.status_code == 201, response.text


def _gif(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("P", (width, height), 0).save(buf, format="GIF")
    return buf.getvalue()


def _animated_gif_with_larger_second_frame() -> bytes:
    """A 10x10 logical screen whose second frame is 20x20.

    Pillow will not write this, so the second frame's image descriptor and
    data are spliced out of a 20x20 GIF and appended before the trailer.
    Pillow grows the canvas to 20x20 when it reaches that frame.
    """
    first = _gif(10, 10)
    larger = _gif(20, 20)
    descriptor = b",\x00\x00\x00\x00\x14\x00\x14\x00"
    frame = larger[larger.index(descriptor) : -1]
    return first[:-1] + frame + b";"


async def _upload_as(client: AsyncClient, content: bytes, ctype: str):  # type: ignore[no-untyped-def]
    return await client.post(API, files={"file": ("anim", content, ctype)})


async def test_a_gif_frame_larger_than_the_screen_is_refused(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    # ``Image.open`` reports only the 10x10 logical screen; the second frame
    # alone is over the limit, and Pillow raises ``DecompressionBombError``
    # on seeking to it.
    content = _animated_gif_with_larger_second_frame()
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with Image.open(io.BytesIO(content)) as image:
        assert image.size == (10, 10)
        assert image.is_animated
        with pytest.raises(Image.DecompressionBombError):
            image.seek(1)

    response = await _upload_as(authed_client, content, "image/gif")

    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "image_too_many_pixels"
    assert _stored_files(tmp_path) == []


async def test_an_animated_gif_within_the_limit_still_uploads(
    authed_client: AsyncClient, monkeypatch
) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 400)

    response = await _upload_as(
        authed_client, _animated_gif_with_larger_second_frame(), "image/gif"
    )

    assert response.status_code == 201, response.text
    # The stored dimensions stay the logical screen's, as before.
    assert (response.json()["width"], response.json()["height"]) == (10, 10)


def _animated(fmt: str, side: int) -> bytes:
    buf = io.BytesIO()
    frames = [Image.new("RGB", (side, side), c) for c in ("red", "blue")]
    frames[0].save(buf, format=fmt, save_all=True, append_images=frames[1:])
    return buf.getvalue()


@pytest.mark.parametrize(("fmt", "ctype"), [("PNG", "image/png"), ("WEBP", "image/webp")])
async def test_an_animated_canvas_over_the_limit_is_refused(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch, fmt: str, ctype: str
) -> None:
    # APNG and animated WebP frames must lie inside the canvas (Pillow and
    # libwebp reject one that does not), so the canvas size bounds them all.
    content = _animated(fmt, 12)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    response = await _upload_as(authed_client, content, ctype)

    assert response.status_code == 413, response.text
    assert _stored_files(tmp_path) == []


async def test_gif_canvas_walks_extensions_and_tolerates_truncation(tmp_path: Path) -> None:
    # Pillow writes loop/duration extensions on every animated GIF; the walk
    # must step over them, and a cut-off file must not raise.
    path = tmp_path / "a.gif"
    path.write_bytes(_animated("GIF", 8))
    assert gif_canvas_size(path) == (8, 8)
    spliced = _animated_gif_with_larger_second_frame()
    path.write_bytes(spliced)
    assert gif_canvas_size(path) == (20, 20)
    # Pillow skips a stray byte between blocks, so the walk must too.
    first = _gif(10, 10)
    padded = first[:-1] + b"\x00" + spliced[len(first) - 1 :]
    path.write_bytes(padded)
    assert gif_canvas_size(path) == (20, 20)
    path.write_bytes(spliced[: len(spliced) // 2])
    assert gif_canvas_size(path) is not None
    path.write_bytes(_png(4, 4))
    assert gif_canvas_size(path) is None
    path.write_bytes(b"GIF89a")
    assert gif_canvas_size(path) is None


def _disguised(kind: str) -> bytes:
    spliced = _animated_gif_with_larger_second_frame()
    cut = len(_gif(10, 10)) - 1  # where the 20x20 frame starts
    if kind == "junk":
        # Bytes that open no block, which Pillow steps over one at a time.
        return spliced[:cut] + b"\x00\x01\x02junk" + spliced[cut:]
    # Cut inside the large frame's pixel data, trailer gone.
    return spliced[: cut + 15]


@pytest.mark.parametrize("kind", ["junk", "truncated"])
async def test_a_large_gif_frame_cannot_hide_behind_junk_or_truncation(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch, kind: str
) -> None:
    # The walk must find every frame Pillow would: if it stopped earlier, the
    # 20x20 frame would pass unseen (security review on #222).
    content = _disguised(kind)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with Image.open(io.BytesIO(content)) as image:
        assert image.size == (10, 10)
        with pytest.raises(Image.DecompressionBombError):
            image.seek(1)

    response = await _upload_as(authed_client, content, "image/gif")

    assert response.status_code == 413, (kind, response.text)
    assert _stored_files(tmp_path) == []


def _with_extension_before_second_frame(extension: bytes) -> bytes:
    # After the first frame, so ``Image.open`` still succeeds and the walk
    # (not Pillow's opening) is what meets the extension.
    spliced = _animated_gif_with_larger_second_frame()
    cut = len(_gif(10, 10)) - 1
    return spliced[:cut] + extension + spliced[cut:]


@pytest.mark.parametrize(
    "extension",
    [
        pytest.param(b"!\xf9\x00", id="control-extension-without-data"),
        pytest.param(b"!\xff\x0bNETSCAPE2.0\x00", id="netscape-without-data"),
    ],
)
async def test_a_gif_pillow_would_read_differently_is_refused(
    authed_client: AsyncClient, tmp_path: Path, extension: bytes
) -> None:
    # Pillow reads past the terminator of these extensions, so where the next
    # block starts is ambiguous; the walk refuses rather than guess (#222).
    content = _with_extension_before_second_frame(extension)

    response = await _upload_as(authed_client, content, "image/gif")

    assert response.status_code == 415, response.text
    assert _stored_files(tmp_path) == []


async def test_a_pillow_written_animated_gif_still_uploads(authed_client: AsyncClient) -> None:
    # Loop (NETSCAPE2.0) and per-frame control extensions, as real encoders write.
    response = await _upload_as(authed_client, _animated("GIF", 8), "image/gif")

    assert response.status_code == 201, response.text


async def test_an_unexpected_processing_error_leaves_no_file(
    authed_client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("pagebuilder.media_service.process_image", boom)

    with pytest.raises(RuntimeError):
        await _upload(authed_client, _png(4, 4))

    assert _stored_files(tmp_path) == []
