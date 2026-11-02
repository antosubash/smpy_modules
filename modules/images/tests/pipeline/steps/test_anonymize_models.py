"""The ONNX models' pre- and post-processing, on fake model outputs."""

from __future__ import annotations

from typing import Any

import pytest
from PIL import Image as PILImage
from sm_images.pipeline.steps.anonymize import models

np = pytest.importorskip("numpy")


def test_nms_keeps_the_best_of_overlapping_boxes():
    boxes = [(0, 0, 10, 10, 0.6), (1, 1, 10, 10, 0.9), (50, 50, 5, 5, 0.3)]
    assert models.nms(boxes, 0.45) == [(1, 1, 10, 10, 0.9), (50, 50, 5, 5, 0.3)]


def test_a_small_frame_is_one_tile_a_large_one_adds_four_overlapping():
    assert list(models._tiles(900, 600, 608)) == [(0, 0, 900, 600)]
    tiles = list(models._tiles(2000, 1000, 608))
    assert tiles[0] == (0, 0, 2000, 1000) and len(tiles) == 5
    # Together the tiles cover the frame, and neighbours overlap.
    assert {(t[0], t[1]) for t in tiles[1:]} == {(0, 0), (800, 0), (0, 400), (800, 400)}
    assert all(t[2] - t[0] == 1200 and t[3] - t[1] == 600 for t in tiles[1:])


def _plate_model(box_in_frame: tuple[float, float, float, float], calls: list[Any]):
    """An end-to-end YOLO that sees a plate at *box_in_frame* (x1, y1, x2, y2 of
    the whole 2000 x 1000 picture) on the full-frame pass only."""

    def run(tensor: Any) -> list[Any]:
        calls.append(tensor.shape)
        assert tensor.dtype == np.float32 and tensor.min() >= 0 and tensor.max() <= 1
        if len(calls) > 1:
            return [np.zeros((0, 7), dtype=np.float32)]
        r = 608 / 2000  # letterbox: 608 x 304, 152 px of grey above and below
        x1, y1, x2, y2 = box_in_frame
        row = [0, x1 * r, y1 * r + 152, x2 * r, y2 * r + 152, 0, 0.8]
        low = [0, 0, 152, 10, 162, 0, 0.1]  # under the threshold
        return [np.array([row, low], dtype=np.float32)]

    return run


def test_plate_boxes_map_back_through_the_letterbox():
    calls: list[Any] = []
    image = PILImage.new("RGB", (2000, 1000), (90, 90, 90))
    found = models.detect_plates(_plate_model((1000, 500, 1200, 560), calls), image, 0.5)
    assert len(calls) == 5 and all(c == (1, 3, 608, 608) for c in calls)
    ((x, y, w, h, score),) = found
    assert (x, y, w, h) == pytest.approx((1000, 500, 200, 60), abs=0.5)
    assert score == pytest.approx(0.8)


def test_plate_boxes_from_a_tile_are_offset_by_the_tile():
    image = PILImage.new("RGB", (2000, 1000))
    seen: list[int] = []

    def run(tensor: Any) -> list[Any]:
        seen.append(1)
        if len(seen) != 5:  # only the last tile, (800, 400)-(2000, 1000), finds it
            return [np.zeros((0, 7), dtype=np.float32)]
        r = 608 / 1200  # the tile letterboxed: 608 x 304, 152 px above
        return [np.array([[0, 100 * r, 50 * r + 152, 200 * r, 80 * r + 152, 0, 0.9]])]

    ((x, y, w, h, _),) = models.detect_plates(run, image, 0.5)
    assert (x, y, w, h) == pytest.approx((900, 450, 100, 30), abs=0.5)


def _yunet(face_at: dict[float, tuple[int, int]], calls: list[Any]):
    """YuNet that finds one 16 x 16 face (stride 8, log-size ln 2) in the given
    stride-8 cell, per pass, keyed by the pass's input width."""

    def run(tensor: Any) -> dict[str, Any]:
        _, channels, h, w = tensor.shape
        calls.append((h, w))
        assert channels == 3 and h % 32 == 0 and w % 32 == 0
        out = {}
        for s in models.FACE_STRIDES:
            n = (h // s) * (w // s)
            out[f"cls_{s}"] = np.zeros((1, n, 1), np.float32)
            out[f"obj_{s}"] = np.zeros((1, n, 1), np.float32)
            out[f"bbox_{s}"] = np.zeros((1, n, 4), np.float32)
            out[f"kps_{s}"] = np.zeros((1, n, 10), np.float32)
        if w in face_at:
            row, col = face_at[w]
            cell = row * (w // 8) + col
            out["cls_8"][0, cell, 0] = out["obj_8"][0, cell, 0] = 0.9
            out["bbox_8"][0, cell] = (0, 0, np.log(2), np.log(2))
        return out

    return run


def test_a_large_picture_gets_a_coarse_face_pass_mapped_back():
    image = PILImage.new("RGB", (1280, 640))
    calls: list[Any] = []
    # Coarse pass: 640 x 320 input; a face in cell (10, 20) -> centre (160, 80)
    # there, (320, 160) in the picture, twice the size.
    boxes = models.detect_faces(_yunet({640: (10, 20)}, calls), image, 0.5)
    assert calls == [(640, 1280), (320, 640)]
    ((x, y, w, h, score),) = boxes
    assert (x, y, w, h) == pytest.approx((304, 144, 32, 32))
    assert score == pytest.approx(0.9)


def test_the_same_face_from_both_passes_is_kept_once():
    image = PILImage.new("RGB", (1280, 640))
    # Full size: cell (20, 39) -> centre (316, 160); coarse: cell (10, 19) ->
    # centre (152, 80) there, (304, 160) here, 32 x 32. Same size at full
    # size too (log-size ln 2 at stride 8 is 16 px, so give it 32 by doubling
    # the cell's log-size): IoU well above 0.3, so NMS keeps one.
    calls: list[Any] = []
    run = _yunet({1280: (20, 39), 640: (10, 19)}, calls)

    def bigger(tensor: Any) -> dict[str, Any]:
        out = run(tensor)
        if tensor.shape[3] == 1280:
            out["bbox_8"][0, 20 * 160 + 39, 2:] = np.log(4)
        return out

    boxes = models.detect_faces(bigger, image, 0.5)
    assert len(boxes) == 1
    assert boxes[0][2] == pytest.approx(32)


def test_a_small_picture_is_run_once_and_padded():
    image = PILImage.new("RGB", (100, 50))
    calls: list[Any] = []
    assert models.detect_faces(_yunet({}, calls), image, 0.5) == []
    assert calls == [(64, 128)]
