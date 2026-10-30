"""The real detectors on real photographs - opt-in (``-m real_models``).

Needs the ``[anonymize]`` extra and network for the pinned weights, so the
default run deselects it (``addopts``) and only ``images-models.yml`` runs it.

The two photographs are CC0 (public domain dedication) from Wikimedia Commons,
scaled to 640 px and re-encoded:

* ``fixtures/real_face.jpg`` - "Fishmonger smiling.jpg" by Wilfredor,
  https://commons.wikimedia.org/wiki/File:Fishmonger_smiling.jpg
* ``fixtures/real_plate.jpg`` - "1995 Honda Civic DX sedan in Harvard Blue
  Pearl, rear right, 07-06-2026.jpg" by Cutlass,
  https://commons.wikimedia.org/wiki/File:1995_Honda_Civic_DX_sedan_in_Harvard_Blue_Pearl,_rear_right,_07-06-2026.jpg
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image as PILImage
from PIL import ImageFilter, ImageStat

pytestmark = pytest.mark.real_models

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(scope="module")
def cache(tmp_path_factory) -> Path:
    """One download of the pinned weights for the module's tests."""
    return tmp_path_factory.mktemp("models")


async def _run(photo: Path, cache: Path):
    pytest.importorskip("onnxruntime")
    from sm_images.pipeline.step import StepContext
    from sm_images.steps.anonymize import AnonymizeParams, AnonymizeStep, OnnxDetector

    data = photo.read_bytes()
    step = AnonymizeStep(detector=OnnxDetector("", cache_dir=cache))
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
    outcome = await step.run(ctx)
    assert outcome.status == "completed", outcome
    assert photo.read_bytes() == data
    (blob,) = written
    return outcome, data, blob


def _assert_blurred(kind: str, outcome, data: bytes, blob: bytes) -> None:
    before = PILImage.open(io.BytesIO(data)).convert("L")
    after = PILImage.open(io.BytesIO(blob)).convert("L")
    assert after.size == before.size
    regions = [r for r in outcome.output["regions"] if r["kind"] == kind]
    assert regions
    for r in regions:
        box = (r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"])
        # The region's detail is gone: far less edge energy than in the original.
        assert edges(after, box) < edges(before, box) / 3


async def test_real_face_blur(cache):
    outcome, data, blob = await _run(FIXTURES / "real_face.jpg", cache)
    assert outcome.output["faces"] >= 1
    assert outcome.output["plates"] == 0
    _assert_blurred("face", outcome, data, blob)


async def test_real_plate_blur(cache):
    outcome, data, blob = await _run(FIXTURES / "real_plate.jpg", cache)
    assert outcome.output["plates"] >= 1
    (plate,) = [r for r in outcome.output["regions"] if r["kind"] == "plate"]
    # On the Civic's boot lid, left of centre: (in a 640 x 398 picture)
    assert 60 < plate["x"] < 140 and 160 < plate["y"] < 220
    _assert_blurred("plate", outcome, data, blob)


def edges(img: PILImage.Image, box: tuple[int, int, int, int]) -> float:
    return ImageStat.Stat(img.crop(box).filter(ImageFilter.FIND_EDGES)).mean[0]
