"""The real detectors on a real photograph - opt-in (``-m real_models``).

Needs the ``[anonymize]`` extra and network for the pinned weights, so the
default run deselects it (``addopts``) and only ``images-models.yml`` runs it.
The photograph is one ultralytics ships in its own package (``zidane.jpg``,
two faces), so nothing is bundled here.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage
from PIL import ImageFilter, ImageStat

pytestmark = pytest.mark.real_models


async def test_real_face_blur(tmp_path):
    pytest.importorskip("torch")
    ultralytics = pytest.importorskip("ultralytics")
    from pathlib import Path

    from sm_images.pipeline.step import StepContext
    from sm_images.steps.anonymize import AnonymizeParams, AnonymizeStep
    from sm_images.steps.anonymize.detectors import YoloDetector

    photo = Path(ultralytics.__file__).parent / "assets" / "zidane.jpg"
    data = photo.read_bytes()
    step = AnonymizeStep(detector=YoloDetector("", cache_dir=tmp_path / "models"))
    written: list[bytes] = []

    async def original() -> bytes:
        return data

    async def write(blob: bytes, kind: str) -> None:
        written.append(blob)

    ctx = StepContext(
        step=step,
        image=SimpleNamespace(),
        params=AnonymizeParams(plates=True),
        tenant_id="default",
        read_display=original,
        read_original=original,
        write_display=write,
    )
    outcome = await step.run(ctx)
    assert outcome.status == "completed", outcome
    assert outcome.output["faces"] >= 1
    assert photo.read_bytes() == data
    (blob,) = written
    before = PILImage.open(io.BytesIO(data)).convert("L")
    after = PILImage.open(io.BytesIO(blob)).convert("L")
    assert after.size == before.size
    for r in outcome.output["regions"]:
        if r["kind"] != "face":
            continue
        box = (r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"])
        # The face's detail is gone: far less edge energy than in the original.
        assert edges(after, box) < edges(before, box) / 3


def edges(img: PILImage.Image, box: tuple[int, int, int, int]) -> float:
    return ImageStat.Stat(img.crop(box).filter(ImageFilter.FIND_EDGES)).mean[0]
