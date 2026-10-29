"""The two ONNX models' pre- and post-processing, in numpy. No onnxruntime here.

* **Faces - YuNet** (OpenCV Zoo, MIT). An anchor-free detector with a dynamic
  input: the picture goes in at its own size, padded to a multiple of 32, BGR,
  unscaled 0-255. Three strides (8, 16, 32) each give, per grid cell, a class
  and an objectness score (the box's score is their geometric mean) and a box
  as an offset from the cell plus a log-scale size. YuNet is trained on faces
  of about 10-300 px, so a large picture is also run scaled down to
  :data:`FACE_COARSE_DIM` (a face filling the frame), and both passes merge.
* **Number plates - YOLOv9 end-to-end** (open-image-models, MIT). A fixed
  square input, letterboxed with grey 114, RGB scaled to 0-1. The graph already
  applies NMS: each output row is ``[batch, x1, y1, x2, y2, class, score]``.
  A picture much larger than the input is also run as 2 x 2 overlapping tiles,
  so a distant plate keeps enough pixels to be found.

Every function answers ``(x, y, w, h, score)`` rows in the coordinates of the
image it was given. The caller turns them into ``Detection`` and checks them.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from PIL import Image

__all__ = [
    "FACE_COARSE_DIM",
    "PLATE_INPUT",
    "Box",
    "MalformedOutput",
    "detect_faces",
    "detect_plates",
    "nms",
]

Box = tuple[float, float, float, float, float]
"""``(x, y, w, h, score)``."""
Run = Callable[[Any], list[Any]]
"""A model: an input tensor in, its output arrays out."""
FaceRun = Callable[[Any], dict[str, Any]]
"""YuNet: an input tensor in, its outputs by name out."""

FACE_STRIDES: Final = (8, 16, 32)
FACE_PARTS: Final = {"cls": 1, "obj": 1, "bbox": 4, "kps": 10}
"""YuNet's outputs per stride, and the width of each row."""
PLATE_COLUMNS: Final = 7
FACE_COARSE_DIM: Final = 640
FACE_NMS_IOU: Final = 0.3
PLATE_INPUT: Final = 608
"""The plate model's square input side (``yolo-v9-s-608``)."""
PLATE_NMS_IOU: Final = 0.45
TILE_OVERLAP: Final = 0.2


class MalformedOutput(ValueError):  # noqa: N818 - reads as the failure it is
    """A model answered something other than its contract (a swapped or broken
    file). The run fails: never "nothing found" for an uninspected picture."""


def _array(value: Any, name: str, shape: tuple[int, ...]) -> Any:
    """*value* as a finite float array of exactly *shape*, or raise."""
    import numpy as np

    if not isinstance(value, np.ndarray) or not np.issubdtype(value.dtype, np.floating):
        raise MalformedOutput(f"{name}: expected a float array, got {type(value).__name__}")
    if value.shape != shape:
        raise MalformedOutput(f"{name}: shape {value.shape}, expected {shape}")
    if not np.isfinite(value).all():
        raise MalformedOutput(f"{name}: non-finite values")
    return value


def nms(boxes: list[Box], iou: float) -> list[Box]:
    """Greedy non-maximum suppression, highest score first."""
    kept: list[Box] = []
    for box in sorted(boxes, key=lambda b: b[4], reverse=True):
        if all(_iou(box, k) <= iou for k in kept):
            kept.append(box)
    return kept


def _iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _scaled(image: Image.Image, scale: float) -> Image.Image:
    from PIL import Image

    if scale == 1.0:
        return image
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.BILINEAR)


# --- faces -------------------------------------------------------------------


def _face_tensor(image: Image.Image) -> tuple[Any, int]:
    import numpy as np

    pw = math.ceil(image.width / 32) * 32
    ph = math.ceil(image.height / 32) * 32
    canvas = np.zeros((ph, pw, 3), dtype=np.float32)
    canvas[: image.height, : image.width] = np.asarray(image, dtype=np.float32)[:, :, ::-1]
    return canvas.transpose(2, 0, 1)[None], pw


def _face_outputs(outputs: dict[str, Any], pw: int, ph: int) -> dict[str, Any]:
    """Every YuNet output present, nothing else, each sized for a *pw* x *ph* input."""
    expected = {f"{part}_{s}" for part in FACE_PARTS for s in FACE_STRIDES}
    if set(outputs) != expected:
        raise MalformedOutput(f"face model outputs {sorted(outputs)}, expected {sorted(expected)}")
    checked = {}
    for name in expected:
        part, stride = name.split("_")
        cells = (pw // int(stride)) * (ph // int(stride))
        checked[name] = _array(outputs[name], name, (1, cells, FACE_PARTS[part]))
    return checked


def _decode_faces(outputs: dict[str, Any], pw: int, conf: float, sx: float, sy: float) -> list[Box]:
    import numpy as np

    out: list[Box] = []
    for stride in FACE_STRIDES:
        cols = pw // stride
        cls = np.clip(outputs[f"cls_{stride}"][0, :, 0], 0, 1)
        obj = np.clip(outputs[f"obj_{stride}"][0, :, 0], 0, 1)
        score = np.sqrt(cls * obj)
        bbox = outputs[f"bbox_{stride}"][0]
        for i in np.nonzero(score >= conf)[0]:
            row, col = divmod(int(i), cols)
            dx, dy, lw, lh = (float(v) for v in bbox[i])
            w, h = math.exp(lw) * stride, math.exp(lh) * stride
            cx, cy = (col + dx) * stride, (row + dy) * stride
            out.append(((cx - w / 2) / sx, (cy - h / 2) / sy, w / sx, h / sy, float(score[i])))
    return out


def detect_faces(
    run: Callable[[Any], dict[str, Any]], image: Image.Image, conf: float
) -> list[Box]:
    """YuNet at full size and, for a large picture, at :data:`FACE_COARSE_DIM`.
    Raises :class:`MalformedOutput` when the model's answer is not YuNet's."""
    scales = [1.0]
    if max(image.size) > FACE_COARSE_DIM:
        scales.append(FACE_COARSE_DIM / max(image.size))
    found: list[Box] = []
    for scale in scales:
        probe = _scaled(image, scale)
        tensor, pw = _face_tensor(probe)
        outputs = _face_outputs(run(tensor), pw, tensor.shape[2])
        # Per axis: width and height were rounded independently.
        sx, sy = probe.width / image.width, probe.height / image.height
        found += _decode_faces(outputs, pw, conf, sx, sy)
    return nms(found, FACE_NMS_IOU)


# --- number plates -----------------------------------------------------------


def _letterbox(image: Image.Image, size: int) -> tuple[Any, float, float, int, int]:
    import numpy as np

    r = size / max(image.size)
    probe = _scaled(image, r)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    dx, dy = (size - probe.width) // 2, (size - probe.height) // 2
    canvas[dy : dy + probe.height, dx : dx + probe.width] = np.asarray(probe)
    tensor = (canvas.transpose(2, 0, 1)[None] / 255.0).astype(np.float32)
    return tensor, probe.width / image.width, probe.height / image.height, dx, dy


def _tiles(w: int, h: int, size: int) -> Iterator[tuple[int, int, int, int]]:
    """The whole frame, then 2 x 2 overlapping tiles when the frame is more than
    1.5 inputs on its long side."""
    yield 0, 0, w, h
    if max(w, h) <= size * 1.5:
        return
    tw = math.ceil(w * (0.5 + TILE_OVERLAP / 2))
    th = math.ceil(h * (0.5 + TILE_OVERLAP / 2))
    for y0 in (0, h - th):
        for x0 in (0, w - tw):
            yield x0, y0, x0 + tw, y0 + th


def _plate_rows(outputs: Any) -> Any:
    """The one ``[n, 7]`` output, finite floats, or raise."""
    if not isinstance(outputs, list | tuple) or len(outputs) != 1:
        raise MalformedOutput("plate model: expected exactly one output")
    rows = outputs[0]
    shape = getattr(rows, "shape", None)
    if shape is None or len(shape) != 2 or shape[1] != PLATE_COLUMNS:
        raise MalformedOutput(f"plate model: output shape {shape}, expected (n, {PLATE_COLUMNS})")
    return _array(rows, "plate output", tuple(shape))


def detect_plates(run: Run, image: Image.Image, conf: float) -> list[Box]:
    """The end-to-end YOLOv9 plate model on the frame (and tiles), merged.
    Raises :class:`MalformedOutput` when the model's answer is not that."""
    found: list[Box] = []
    for x0, y0, x1, y1 in _tiles(image.width, image.height, PLATE_INPUT):
        crop = image if (x0, y0, x1, y1) == (0, 0, *image.size) else image.crop((x0, y0, x1, y1))
        tensor, rx, ry, dx, dy = _letterbox(crop, PLATE_INPUT)
        for row in _plate_rows(run(tensor)):
            bx1, by1, bx2, by2, score = (float(v) for v in (*row[1:5], row[6]))
            if score < conf:
                continue
            x, y = (bx1 - dx) / rx + x0, (by1 - dy) / ry + y0
            found.append((x, y, (bx2 - bx1) / rx, (by2 - by1) / ry, score))
    return nms(found, PLATE_NMS_IOU)
