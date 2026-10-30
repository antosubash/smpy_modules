"""A fake ``onnxruntime`` whose two sessions answer through swappable functions,
and a runner for the ``anonymize`` step on the default (ONNX) detector.

Default CI has no onnxruntime: these fakes stand in for it so the step's
handling of what a model returns - valid or not - is tested without weights.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import numpy as np
from sm_images.pipeline.step import StepContext, StepOutcome
from sm_images.steps.anonymize import AnonymizeParams, AnonymizeStep

FACE_OUTPUTS = [f"{part}_{s}" for part in ("cls", "obj", "bbox", "kps") for s in (8, 16, 32)]
WIDTHS = {"cls": 1, "obj": 1, "bbox": 4, "kps": 10}


def no_faces(tensor: Any) -> list[Any]:
    """YuNet's outputs, all zero, sized for *tensor*: a valid "nothing here"."""
    _, _, h, w = tensor.shape
    out = []
    for name in FACE_OUTPUTS:
        part, stride = name.split("_")
        n = (h // int(stride)) * (w // int(stride))
        out.append(np.zeros((1, n, WIDTHS[part]), dtype=np.float32))
    return out


def no_plates(tensor: Any) -> list[Any]:
    return [np.zeros((0, 7), dtype=np.float32)]


def content_box(tensor: Any) -> list[Any]:
    """A plate model that answers one box around everything that is not the
    letterbox's grey: the picture itself, in letterbox pixels."""
    grey = np.isclose(tensor[0], 114 / 255.0).all(axis=0)
    ys, xs = np.nonzero(~grey)
    row = [0, xs.min(), ys.min(), xs.max() + 1, ys.max() + 1, 0, 0.9]
    return [np.array([row], dtype=np.float32)]


class FakeOrt:
    """Install with :meth:`install`; set ``face`` / ``plate`` to change answers."""

    def __init__(self) -> None:
        self.face: Callable[[Any], list[Any]] = no_faces
        self.plate: Callable[[Any], list[Any]] = no_plates
        self.face_names = list(FACE_OUTPUTS)
        self.created = 0

    def install(self, monkeypatch) -> None:
        from sm_images.steps.anonymize import detectors

        fake = self

        class Session:
            def __init__(self, data: bytes, *, providers: list[str]) -> None:
                fake.created += 1
                self.kind = "face" if data == b"face" else "plate"

            def get_inputs(self):
                return [SimpleNamespace(name="input")]

            def get_outputs(self):
                names = fake.face_names if self.kind == "face" else ["output0"]
                return [SimpleNamespace(name=n) for n in names]

            def run(self, names, feed: dict[str, Any]) -> list[Any]:
                (tensor,) = feed.values()
                return (fake.face if self.kind == "face" else fake.plate)(tensor)

        module = types.ModuleType("onnxruntime")
        module.InferenceSession = Session  # type: ignore[attr-defined]
        module.get_available_providers = lambda: ["CPUExecutionProvider"]  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "onnxruntime", module)
        monkeypatch.setattr(detectors, "_shared", {})


def weights_dir(tmp_path) -> str:
    (tmp_path / "face.onnx").write_bytes(b"face")
    (tmp_path / "plate.onnx").write_bytes(b"plate")
    return str(tmp_path)


async def run_step(data: bytes, weights: str, **params: Any) -> tuple[StepOutcome, list[bytes]]:
    """The step on its default detector, ``anonymize_weights_path=weights``."""
    step = AnonymizeStep()
    written: list[bytes] = []

    async def original() -> bytes:
        return data

    async def write(blob: bytes, kind: str) -> None:
        written.append(blob)

    ctx = StepContext(
        step=step,
        image=SimpleNamespace(),
        params=AnonymizeParams(**params),
        tenant_id="default",
        read_display=original,
        read_original=original,
        write_display=write,
    )
    ctx._staging = SimpleNamespace(settings=SimpleNamespace(anonymize_weights_path=weights))
    return await step.run(ctx), written
