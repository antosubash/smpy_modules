"""The default detector, wired from the settings, on a fake ``onnxruntime``.

Default CI has no onnxruntime; a stand-in module checks what the step hands
the real library: ``anonymize_weights_path`` from the worker's settings, one
session per kind, loaded once, and the outputs decoded back into boxes.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from sm_images.pipeline.step import StepContext
from sm_images.steps.anonymize import AnonymizeParams, AnonymizeStep, detectors

from tests.anonymize_support import picture

np = pytest.importorskip("numpy")

FACE_OUTPUTS = [f"{part}_{s}" for part in ("cls", "obj", "bbox", "kps") for s in (8, 16, 32)]
_WIDTHS = {"cls": 1, "obj": 1, "bbox": 4, "kps": 10}


def _face_outputs(tensor: Any) -> list[Any]:
    """YuNet's outputs for a padded input: one face, 8 x 8 px, in the stride-8
    cell at row 3, column 3 - the box (24, 20, 8, 8) in the 64 x 48 picture."""
    _, _, h, w = tensor.shape
    out = []
    for name in FACE_OUTPUTS:
        part, stride = name.split("_")
        cols, rows = w // int(stride), h // int(stride)
        arr = np.zeros((1, rows * cols, _WIDTHS[part]), dtype=np.float32)
        if stride == "8":
            cell = 3 * cols + 3
            if part in ("cls", "obj"):
                arr[0, cell, 0] = 0.81  # score sqrt(0.81 * 0.81) = 0.81
            elif part == "bbox":
                arr[0, cell] = (0.5, 0.0, 0.0, 0.0)  # centre (28, 24), size 8 x 8
        out.append(arr)
    return out


class FakeSession:
    loaded: ClassVar[list[bytes]] = []

    def __init__(self, data: bytes, *, providers: list[str]) -> None:
        assert providers == ["CPUExecutionProvider"]
        FakeSession.loaded.append(data)
        self.face = data == b"face weights"

    def get_inputs(self):
        return [SimpleNamespace(name="input" if self.face else "images")]

    def get_outputs(self):
        names = FACE_OUTPUTS if self.face else ["output0"]
        return [SimpleNamespace(name=n) for n in names]

    def run(self, names, feed: dict[str, Any]) -> list[Any]:
        assert names is None
        (tensor,) = feed.values()
        if self.face:
            return _face_outputs(tensor)
        assert tensor.shape == (1, 3, 608, 608)
        return [np.zeros((0, 7), dtype=np.float32)]


@pytest.fixture
def fake_onnxruntime(monkeypatch):
    module = types.ModuleType("onnxruntime")
    module.InferenceSession = FakeSession  # type: ignore[attr-defined]
    module.get_available_providers = lambda: ["CPUExecutionProvider"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", module)
    monkeypatch.setattr(detectors, "_shared", {})
    FakeSession.loaded = []
    return FakeSession


async def _run(weights_dir: str):
    step = AnonymizeStep()  # no injected detector: the default one
    written: list[bytes] = []
    data = picture()

    async def original() -> bytes:
        return data

    async def write(blob: bytes, kind: str) -> None:
        written.append(blob)

    ctx = StepContext(
        step=step,
        image=SimpleNamespace(),
        params=AnonymizeParams(padding=0),
        tenant_id="default",
        read_display=original,
        read_original=original,
        write_display=write,
    )
    ctx._staging = SimpleNamespace(settings=SimpleNamespace(anonymize_weights_path=weights_dir))
    return await step.run(ctx), written


async def test_the_setting_reaches_the_detector(tmp_path, fake_onnxruntime):
    (tmp_path / "face.onnx").write_bytes(b"face weights")
    (tmp_path / "plate.onnx").write_bytes(b"plate weights")
    outcome, written = await _run(str(tmp_path))
    assert outcome.status == "completed", outcome
    assert fake_onnxruntime.loaded == [b"face weights", b"plate weights"]
    assert outcome.output["regions"] == [
        {"kind": "face", "x": 24, "y": 20, "w": 8, "h": 8, "score": 0.81}
    ]
    assert len(written) == 1
    # A second image reuses the loaded sessions.
    await _run(str(tmp_path))
    assert len(fake_onnxruntime.loaded) == 2


async def test_a_configured_directory_missing_weights_fails_the_run(tmp_path, fake_onnxruntime):
    outcome, written = await _run(str(tmp_path))
    assert (outcome.status, outcome.code) == ("failed", "weights_unavailable")
    assert fake_onnxruntime.loaded == [] and written == []


async def test_old_pt_weights_are_not_picked_up(tmp_path, fake_onnxruntime):
    """A directory still holding the former YOLO ``.pt`` files fails closed."""
    for name in ("face.pt", "plate.pt"):
        (tmp_path / name).write_bytes(b"weights")
    outcome, _ = await _run(str(tmp_path))
    assert (outcome.status, outcome.code) == ("failed", "weights_unavailable")
