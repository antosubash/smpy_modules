"""Boxes map back per axis. Resizing rounds width and height independently, so
an extreme aspect ratio has two different scales; one scale for both would
shift a box by many pixels on the short side's axis (or the long one's)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image as PILImage
from sm_images.steps.anonymize import models

np = pytest.importorskip("numpy")

from tests.onnx_support import FakeOrt, content_box, weights_dir  # noqa: E402
from tests.onnx_support import run_step as run  # noqa: E402


def _approx(box: models.Box, expected: tuple[float, float, float, float]) -> bool:
    return all(abs(a - b) <= 1 for a, b in zip(box[:4], expected, strict=True))


@pytest.mark.parametrize("size", [(101, 1600), (1600, 101), (37, 900), (900, 37)])
def test_a_full_frame_plate_maps_back_to_the_picture_edges(size):
    image = PILImage.new("RGB", size, (200, 20, 20))
    boxes = models.detect_plates(content_box, image, 0.5)
    assert any(_approx(b, (0, 0, *size)) for b in boxes), boxes


def _full_probe_face(tensor: Any) -> dict[str, Any]:
    """YuNet answering one face exactly the size of the unpadded probe (the
    red pixels), centred on it, in the stride-32 cell holding its centre."""
    _, _, h, w = tensor.shape
    red = tensor[0, 2] > 0  # BGR: red channel last
    ys, xs = np.nonzero(red)
    pw, ph = xs.max() + 1, ys.max() + 1
    out = {}
    for s in models.FACE_STRIDES:
        n = (h // s) * (w // s)
        out[f"cls_{s}"] = np.zeros((1, n, 1), np.float32)
        out[f"obj_{s}"] = np.zeros((1, n, 1), np.float32)
        out[f"bbox_{s}"] = np.zeros((1, n, 4), np.float32)
        out[f"kps_{s}"] = np.zeros((1, n, 10), np.float32)
    cx, cy = pw / 2, ph / 2
    row, col = int(cy // 32), int(cx // 32)
    cell = row * (w // 32) + col
    out["cls_32"][0, cell, 0] = out["obj_32"][0, cell, 0] = 0.9
    out["bbox_32"][0, cell] = (cx / 32 - col, cy / 32 - row, np.log(pw / 32), np.log(ph / 32))
    return out


@pytest.mark.parametrize("size", [(4000, 61), (61, 4000)])
def test_the_coarse_face_pass_maps_back_per_axis(size):
    image = PILImage.new("RGB", size, (200, 20, 20))
    calls: list[tuple[int, ...]] = []

    def run_once_coarse(tensor: Any) -> dict[str, Any]:
        calls.append(tensor.shape)
        if len(calls) == 1:  # the full-size pass: nothing
            out = _full_probe_face(tensor)
            for s in models.FACE_STRIDES:
                out[f"cls_{s}"][:] = 0
            return out
        return _full_probe_face(tensor)

    boxes = models.detect_faces(run_once_coarse, image, 0.5)
    assert len(calls) == 2
    assert any(_approx(b, (0, 0, *size)) for b in boxes), boxes


async def test_an_exif_rotated_portrait_plate_maps_to_the_upright_edges(tmp_path, monkeypatch):
    ort = FakeOrt()
    ort.install(monkeypatch)
    ort.plate = content_box
    # Stored 1600 x 102 landscape, orientation 6: displayed as 102 x 1600. The
    # letterbox makes it 39 x 608 (102 x 0.38 = 38.76 rounds up), so one scale
    # for both axes would end the box at y = 1590 - not hidden by clamping.
    img = PILImage.new("RGB", (1600, 102), (200, 20, 20))
    exif = PILImage.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, exif=exif.tobytes())
    outcome, written = await run(buf.getvalue(), weights_dir(tmp_path), faces=False, padding=0)
    assert outcome.status == "completed", outcome
    regions = outcome.output["regions"]
    assert any(
        abs(r["x"]) <= 1 and abs(r["y"]) <= 1 and abs(r["w"] - 102) <= 1 and abs(r["h"] - 1600) <= 1
        for r in regions
    ), regions
    assert len(written) == 1
