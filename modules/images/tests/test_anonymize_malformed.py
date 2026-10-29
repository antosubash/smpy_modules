"""A model that answers something other than what the step expects - a swapped
or broken file - fails the run. It never reads as "nothing found", which would
publish the original unblurred."""

from __future__ import annotations

from typing import Any

import pytest

np = pytest.importorskip("numpy")

from tests.anonymize_support import picture  # noqa: E402
from tests.onnx_support import FakeOrt, no_faces, weights_dir  # noqa: E402
from tests.onnx_support import run_step as run  # noqa: E402


@pytest.fixture
def ort(monkeypatch) -> FakeOrt:
    fake = FakeOrt()
    fake.install(monkeypatch)
    return fake


def _poke(name: str, value: float, *, index: tuple[int, ...] = (0, 0, 0)):
    def face(tensor: Any) -> list[Any]:
        out = no_faces(tensor)
        out[[f"{p}_{s}" for p in ("cls", "obj", "bbox", "kps") for s in (8, 16, 32)].index(name)][
            index
        ] = value
        return out

    return face


def _reshape(name: str, new: Any):
    names = [f"{p}_{s}" for p in ("cls", "obj", "bbox", "kps") for s in (8, 16, 32)]

    def face(tensor: Any) -> list[Any]:
        out = no_faces(tensor)
        out[names.index(name)] = new(out[names.index(name)])
        return out

    return face


FACE_CASES = {
    "nan score": _poke("cls_8", float("nan")),
    "nan objectness": _poke("obj_32", float("nan")),
    "inf box": _poke("bbox_16", float("inf"), index=(0, 0, 2)),
    "grid too small": _reshape("cls_8", lambda a: a[:, :-1]),
    "grid empty": _reshape("bbox_8", lambda a: a[:, :0]),
    "wrong box width": _reshape("bbox_32", lambda a: np.zeros((1, a.shape[1], 5), np.float32)),
    "wrong rank": _reshape("obj_16", lambda a: a[0]),
    "integer dtype": _reshape("cls_16", lambda a: a.astype(np.int64)),
    "an output missing": lambda t: no_faces(t)[:-1],
}

PLATE_CASES = {
    "empty with 6 columns": lambda t: [np.zeros((0, 6), np.float32)],
    "6 columns": lambda t: [np.ones((1, 6), np.float32)],
    "rank 3": lambda t: [np.zeros((1, 0, 7), np.float32)],
    "two outputs": lambda t: [np.zeros((0, 7), np.float32)] * 2,
    "no output": lambda t: [],
    "nan score": lambda t: [np.array([[0, 1, 1, 9, 9, 0, np.nan]], np.float32)],
    "inf box": lambda t: [np.array([[0, 1, 1, np.inf, 9, 0, 0.9]], np.float32)],
    "nan below threshold": lambda t: [np.array([[0, np.nan, 1, 9, 9, 0, 0.1]], np.float32)],
    "string dtype": lambda t: [np.array([["a"] * 7])],
}


@pytest.mark.parametrize("case", FACE_CASES)
async def test_a_malformed_face_output_fails_closed(tmp_path, ort, case):
    ort.face = FACE_CASES[case]
    outcome, written = await run(picture(), weights_dir(tmp_path), plates=False)
    assert (outcome.status, outcome.code) == ("failed", "detection_failed"), outcome
    assert written == []


@pytest.mark.parametrize("case", PLATE_CASES)
async def test_a_malformed_plate_output_fails_closed(tmp_path, ort, case):
    ort.plate = PLATE_CASES[case]
    outcome, written = await run(picture(), weights_dir(tmp_path), faces=False)
    assert (outcome.status, outcome.code) == ("failed", "detection_failed"), outcome
    assert written == []


async def test_a_face_model_with_extra_outputs_fails_closed(tmp_path, ort):
    ort.face_names = [*ort.face_names, "extra"]
    ort.face = lambda t: [*no_faces(t), np.zeros((1, 1, 1), np.float32)]
    outcome, written = await run(picture(), weights_dir(tmp_path), plates=False)
    assert (outcome.status, outcome.code) == ("failed", "detection_failed")
    assert written == []


async def test_valid_empty_outputs_complete_with_nothing_found(tmp_path, ort):
    outcome, written = await run(picture(), weights_dir(tmp_path))
    assert outcome.status == "completed", outcome
    assert outcome.output["regions"] == [] and written == []
