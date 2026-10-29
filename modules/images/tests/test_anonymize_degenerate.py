"""A confident box that cannot be blurred - no width, no height, or far outside
what the model was shown - is a broken model, not "nothing found": the run
fails closed. The same box under the threshold is noise and is ignored."""

from __future__ import annotations

from typing import Any

import pytest
from sm_images.steps.anonymize import Detection

from tests.anonymize_support import FakeDetector, picture, use_anonymize

np = pytest.importorskip("numpy")

from tests.onnx_support import FACE_OUTPUTS, FakeOrt, no_faces, weights_dir  # noqa: E402
from tests.onnx_support import run_step as run  # noqa: E402


@pytest.fixture
def ort(monkeypatch) -> FakeOrt:
    fake = FakeOrt()
    fake.install(monkeypatch)
    return fake


PLATE_BOXES = {
    "zero width": (10, 10, 10, 20),
    "zero height": (10, 10, 30, 10),
    "negative width": (30, 10, 10, 20),
    "far right": (10, 10, 5000, 20),
    "far left": (-1000, 10, 20, 20),
    "far below": (10, 10, 20, 9000),
}


def _plate(box: tuple[float, ...], score: float):
    return lambda t: [np.array([[0, *box, 0, score]], np.float32)]


@pytest.mark.parametrize("case", PLATE_BOXES)
async def test_a_confident_degenerate_plate_fails_closed(tmp_path, ort, case):
    ort.plate = _plate(PLATE_BOXES[case], 0.9)
    outcome, written = await run(picture(), weights_dir(tmp_path), faces=False)
    assert (outcome.status, outcome.code) == ("failed", "detection_failed"), outcome
    assert written == []


@pytest.mark.parametrize("case", PLATE_BOXES)
async def test_a_degenerate_plate_under_the_threshold_is_ignored(tmp_path, ort, case):
    ort.plate = _plate(PLATE_BOXES[case], 0.1)
    outcome, written = await run(picture(), weights_dir(tmp_path), faces=False)
    assert outcome.status == "completed", outcome
    assert outcome.output["regions"] == [] and written == []


FACE_BOXES = {
    # (dx, dy, log w, log h) of the stride-8 cell at row 1, column 1
    "zero width": (0.5, 0.5, -800.0, 0.0),
    "zero height": (0.5, 0.5, 0.0, -800.0),
    "far outside": (5000.0, 0.5, 0.0, 0.0),
    "huge": (0.5, 0.5, 30.0, 30.0),
}


def _face(bbox: tuple[float, ...], score: float):
    def run_face(tensor: Any) -> list[Any]:
        out = no_faces(tensor)
        cols = tensor.shape[3] // 8
        cell = cols + 1
        out[FACE_OUTPUTS.index("cls_8")][0, cell, 0] = score
        out[FACE_OUTPUTS.index("obj_8")][0, cell, 0] = score
        out[FACE_OUTPUTS.index("bbox_8")][0, cell] = bbox
        return out

    return run_face


@pytest.mark.parametrize("case", FACE_BOXES)
async def test_a_confident_degenerate_face_fails_closed(tmp_path, ort, case):
    ort.face = _face(FACE_BOXES[case], 0.9)
    outcome, written = await run(picture(), weights_dir(tmp_path), plates=False)
    assert (outcome.status, outcome.code) == ("failed", "detection_failed"), outcome
    assert written == []


@pytest.mark.parametrize("case", FACE_BOXES)
async def test_a_degenerate_face_under_the_threshold_is_ignored(tmp_path, ort, case):
    ort.face = _face(FACE_BOXES[case], 0.1)
    outcome, written = await run(picture(), weights_dir(tmp_path), plates=False)
    assert outcome.status == "completed", outcome
    assert outcome.output["regions"] == [] and written == []


async def test_a_plate_slightly_past_the_input_edge_still_blurs(tmp_path, ort):
    """A plate cut by the frame is predicted whole: a little past the input is
    within tolerance and blurred, clamped to the picture."""
    ort.plate = _plate((-20, 200, 120, 260), 0.9)
    outcome, written = await run(picture(), weights_dir(tmp_path), faces=False)
    assert outcome.status == "completed", outcome
    assert outcome.output["plates"] == 1 and len(written) == 1


async def _injected(found: list[Detection]):
    from types import SimpleNamespace

    from sm_images.pipeline import registry
    from sm_images.pipeline.step import StepContext
    from sm_images.steps.anonymize import AnonymizeParams

    use_anonymize(FakeDetector(found))
    step = registry.get_step("anonymize")
    data = picture()
    written: list[bytes] = []

    async def original() -> bytes:
        return data

    async def write(blob: bytes, kind: str) -> None:
        written.append(blob)

    ctx = StepContext(
        step=step,
        image=SimpleNamespace(),
        params=AnonymizeParams(),
        tenant_id="default",
        read_display=original,
        read_original=original,
        write_display=write,
    )
    return await step.run(ctx), written


@pytest.mark.parametrize("w,h", [(0, 5), (5, 0)])
async def test_an_injected_detector_s_confident_empty_box_fails_closed(w, h):
    outcome, written = await _injected([Detection("plate", 5, 5, w, h, 0.9)])
    assert (outcome.status, outcome.code) == ("failed", "detection_failed")
    assert written == []


async def test_an_injected_detector_s_unconfident_empty_box_is_ignored():
    outcome, written = await _injected([Detection("plate", 5, 5, 0, 5, 0.1)])
    assert outcome.status == "completed" and written == []
