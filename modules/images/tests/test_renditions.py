from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from sm_images.processing.renditions import make_renditions

FIX = Path(__file__).parent / "fixtures"
SIZES = {"s": 32, "m": 64, "l": 1024}


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_never_enlarges_and_keeps_aspect() -> None:
    out = make_renditions((FIX / "geotagged.jpg").read_bytes(), SIZES)  # 96x64
    assert set(out) == {"s", "m", "l"}
    assert [out[k][1:] for k in ("s", "m", "l")] == [(32, 21), (64, 43), (96, 64)]
    for data, w, h in out.values():
        im = _open(data)
        assert im.format == "JPEG" and im.size == (w, h)


def test_orientation_applied_and_metadata_stripped() -> None:
    out = make_renditions((FIX / "rotated.jpg").read_bytes(), {"a": 1024, "b": 20})  # 80x40, rot 6
    assert out["a"][1:] == (40, 80)
    assert out["b"][1:] == (10, 20)
    assert len(_open(out["a"][0]).getexif()) == 0


def test_transparent_png_composited_on_white() -> None:
    data, w, h = make_renditions((FIX / "transparent.png").read_bytes(), {"a": 40})["a"]
    im = _open(data).convert("RGB")
    assert (w, h) == (40, 40)
    assert all(c > 240 for c in im.getpixel((35, 20)))  # transparent half -> white
    r, g, b = im.getpixel((5, 20))
    assert r > 200 and g < 60 and b < 60


def test_palette_image_composited() -> None:
    buf = io.BytesIO()
    pal = Image.new("P", (10, 10))
    pal.info["transparency"] = 0
    pal.save(buf, "PNG")
    data = make_renditions(buf.getvalue(), {"a": 10})["a"][0]
    assert all(c > 240 for c in _open(data).convert("RGB").getpixel((5, 5)))


def test_heic_input() -> None:
    out = make_renditions((FIX / "sample.heic").read_bytes(), {"a": 32})
    assert out["a"][1:] == (32, 24)


def test_undecodable_raises_no_partial() -> None:
    with pytest.raises(Exception):  # noqa: B017
        make_renditions(b"not an image", SIZES)


def test_empty_sizes_returns_empty() -> None:
    assert make_renditions((FIX / "geotagged.jpg").read_bytes(), {}) == {}


@pytest.mark.parametrize("bad", [0, -5])
def test_non_positive_size_rejected(bad: int) -> None:
    with pytest.raises(ValueError):
        make_renditions((FIX / "geotagged.jpg").read_bytes(), {"a": bad})
