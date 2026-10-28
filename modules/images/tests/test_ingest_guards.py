"""What an upload is (magic bytes), and the refusals before anything is stored."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image as PILImage
from sm_images import constants
from sm_images.errors import ImageTooLarge, UnsupportedType
from sm_images.ingest import guard_pixels, sniff

from tests.upload_support import (
    all_rows,
    heic,
    intents,
    jpeg,
    make_collection,
    picture,
    png,
    post_files,
    stored,
)

LOCALES = Path(__file__).resolve().parents[1] / "sm_images" / "locales"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (jpeg(), "image/jpeg"),
        (png(), "image/png"),
        (picture("WEBP"), "image/webp"),
        (picture("TIFF"), "image/tiff"),
        (heic(), "image/heic"),
        (b"GIF89a" + b"\0" * 20, None),
        (b"%PDF-1.7", None),
        (b"", None),
    ],
)
def test_sniff_reads_magic_bytes(data, expected):
    assert sniff(data) == expected


async def test_magic_bytes_not_extension(uploads):
    """A PNG named ``.jpg`` and declared ``image/jpeg`` is stored and typed as a PNG."""
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("holiday.jpg", png(), "image/jpeg")])
    assert got.status_code == 200, got.text
    (row,) = await all_rows(uploads)
    assert row.content_type == "image/png"
    assert row.storage_key.endswith("/original.png")
    assert row.filename == "holiday.jpg"
    assert stored(uploads.storage) == [row.storage_key]


async def test_unknown_type_415(uploads):
    """A non-image named ``.png`` with an image content type is refused, unstored."""
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("evil.png", b"<?php echo 1; ?>" * 10, "image/png")])
    assert got.status_code == 415, got.text
    assert got.json()["code"] == constants.CODE_UNSUPPORTED_TYPE
    assert await all_rows(uploads) == []
    assert stored(uploads.storage) == []


async def test_truncated_image_is_415_not_500(uploads):
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("cut.png", png()[:40], "image/png")])
    assert got.status_code == 415, got.text


@pytest.mark.parametrize("side", [20, 12], ids=["over-2x-bomb-error", "1x-2x-warning"])
def test_guard_pixels_refuses_both_bands(monkeypatch, side):
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ImageTooLarge):
        guard_pixels(png(size=(side, side)))


def test_guard_pixels_at_the_limit_and_switched_off(monkeypatch):
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 100)
    assert guard_pixels(png(size=(10, 10))) == (10, 10)
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", None)
    assert guard_pixels(png(size=(40, 40))) == (40, 40)


def test_guard_pixels_rejects_garbage():
    with pytest.raises(UnsupportedType):
        guard_pixels(b"\x89PNG\r\n\x1a\n" + b"\0" * 30)


async def test_bomb_pixels_413_translated(uploads, monkeypatch):
    """pagebuilder #221's behaviour: 413, code ``image_too_many_pixels``, nothing
    stored, and a sentence for that code in every catalogue."""
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 100)
    cid = await make_collection(uploads)
    got = await post_files(uploads, cid, [("huge.png", png(size=(20, 20)), "image/png")])
    assert got.status_code == 413, got.text
    assert got.json()["code"] == constants.CODE_TOO_MANY_PIXELS == "image_too_many_pixels"
    assert await all_rows(uploads) == []
    assert stored(uploads.storage) == []
    assert await intents(uploads) == []  # refused before an intent was recorded

    for lang in ("en", "de"):
        catalogue = json.loads((LOCALES / f"{lang}.json").read_text())
        for code in constants.ERROR_CODES:
            assert catalogue["errors"][code].strip(), (lang, code)
    en = json.loads((LOCALES / "en.json").read_text())["errors"]
    de = json.loads((LOCALES / "de.json").read_text())["errors"]
    assert en[constants.CODE_TOO_MANY_PIXELS] != de[constants.CODE_TOO_MANY_PIXELS]
