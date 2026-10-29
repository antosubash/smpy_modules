"""The default detector, wired from the settings, on a fake ``ultralytics``.

Default CI has no torch or ultralytics; a stand-in module checks what the
step hands the real library: ``anonymize_weights_path`` from the worker's
settings, one model per kind, loaded once, and the boxes read back.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import ClassVar

import pytest
from sm_images.pipeline.step import StepContext
from sm_images.steps.anonymize import AnonymizeParams, AnonymizeStep, detectors

from tests.anonymize_support import picture


class _List(list):
    def tolist(self) -> list:
        return list(self)


class FakeYOLO:
    loaded: ClassVar[list[str]] = []

    def __init__(self, path: str) -> None:
        FakeYOLO.loaded.append(path)
        self.path = path

    def predict(self, image, *, conf: float, verbose: bool):
        assert verbose is False and conf == 0.5
        if self.path.endswith("face.pt"):
            boxes = SimpleNamespace(xyxy=_List([[24, 18, 40, 30]]), conf=_List([0.9]))
        else:
            boxes = SimpleNamespace(xyxy=_List([]), conf=_List([]))
        return [SimpleNamespace(boxes=boxes)]


@pytest.fixture
def fake_ultralytics(monkeypatch):
    module = types.ModuleType("ultralytics")
    module.YOLO = FakeYOLO  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ultralytics", module)
    monkeypatch.setattr(detectors, "_shared", {})
    FakeYOLO.loaded = []
    return FakeYOLO


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


async def test_the_setting_reaches_the_detector(tmp_path, fake_ultralytics):
    for name in ("face.pt", "plate.pt"):
        (tmp_path / name).write_bytes(b"weights")
    outcome, written = await _run(str(tmp_path))
    assert outcome.status == "completed", outcome
    assert fake_ultralytics.loaded == [str(tmp_path / "face.pt"), str(tmp_path / "plate.pt")]
    assert outcome.output["regions"] == [
        {"kind": "face", "x": 24, "y": 18, "w": 16, "h": 12, "score": 0.9}
    ]
    assert len(written) == 1
    # A second image reuses the loaded models.
    await _run(str(tmp_path))
    assert len(fake_ultralytics.loaded) == 2


async def test_a_configured_directory_missing_weights_fails_the_run(tmp_path, fake_ultralytics):
    outcome, written = await _run(str(tmp_path))
    assert (outcome.status, outcome.code) == ("failed", "weights_unavailable")
    assert fake_ultralytics.loaded == [] and written == []
