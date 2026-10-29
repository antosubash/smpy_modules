"""The ``anonymize`` step on a fake detector: what it blurs, writes and reports.

Ported from the portal's ``test_anonymization.py``/``test_anonymization_bbox.py``,
with the module's rule in place of the portal's overwrite: the original is
never touched, the blurred picture is a display copy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image as PILImage
from sm_images.pipeline import extensions, registry
from sm_images.pipeline.step import StepContext
from sm_images.steps.anonymize import AnonymizeParams, AnonymizeStep, Detection
from sm_images.steps.anonymize.blur import pad_and_clamp

from tests.anonymize_support import FakeDetector, decode, picture

FACE = Detection("face", 24, 18, 16, 12, 0.9)
"""Covers the white square of a 64x48 ``picture()``."""


async def run(detector, data: bytes | None = None, **params):
    step = AnonymizeStep(detector=detector)
    data = picture() if data is None else data
    written: list[tuple[bytes, str]] = []

    async def original() -> bytes:
        return data

    async def write(blob: bytes, kind: str) -> None:
        written.append((blob, kind))

    ctx = StepContext(
        step=step,
        image=SimpleNamespace(),
        params=AnonymizeParams(**params),
        tenant_id="default",
        read_display=original,
        read_original=original,
        write_display=write,
    )
    return await step.run(ctx), written


def test_params_defaults_and_bounds():
    assert AnonymizeParams().model_dump() == {
        "faces": True,
        "plates": True,
        "padding": 0.15,
        "min_confidence": 0.5,
    }
    for bad in ({"padding": -0.1}, {"padding": 3}, {"min_confidence": 1.5}, {"nope": 1}):
        with pytest.raises(ValueError):
            AnonymizeParams(**bad)


async def test_blur_single_region_writes_a_jpeg_display():
    outcome, written = await run(FakeDetector([FACE]), padding=0)
    assert outcome.status == "completed"
    assert outcome.output == {
        "regions": [{"kind": "face", "x": 24, "y": 18, "w": 16, "h": 12, "score": 0.9}],
        "faces": 1,
        "plates": 0,
    }
    ((blob, kind),) = written
    assert kind == "image/jpeg"
    shown, before = decode(blob), decode(picture())
    assert shown.size == before.size
    # Inside the region the checkered detail is gone; far outside, untouched.
    assert detail(shown, (24, 18, 40, 30)) < detail(before, (24, 18, 40, 30)) / 4
    far = zip(shown.getpixel((2, 2)), before.getpixel((2, 2)), strict=True)
    assert sum(abs(a - b) for a, b in far) < 30


def detail(img: PILImage.Image, box: tuple[int, int, int, int]) -> float:
    from PIL import ImageStat

    return ImageStat.Stat(img.crop(box).convert("L")).stddev[0]


async def test_no_detection_completes_without_a_display_copy():
    outcome, written = await run(FakeDetector([]))
    assert outcome.status == "completed"
    assert outcome.output == {"regions": [], "faces": 0, "plates": 0}
    assert written == []


async def test_face_and_plate_detection_can_each_be_disabled():
    plate = Detection("plate", 2, 2, 10, 5, 0.8)
    fake = FakeDetector([FACE, plate])
    outcome, _ = await run(fake, faces=False)
    assert (outcome.output["faces"], outcome.output["plates"]) == (0, 1)
    assert fake.calls[-1]["faces"] is False and fake.calls[-1]["plates"] is True
    outcome, _ = await run(fake, plates=False)
    assert (outcome.output["faces"], outcome.output["plates"]) == (1, 0)


async def test_both_disabled_is_a_skip_and_runs_no_detector():
    fake = FakeDetector([FACE])
    outcome, written = await run(fake, faces=False, plates=False)
    assert (outcome.status, outcome.reason) == ("skipped", "nothing_to_detect")
    assert fake.calls == [] and written == []


async def test_detections_below_min_confidence_are_ignored():
    weak = Detection("face", 24, 18, 16, 12, 0.3)
    outcome, written = await run(FakeDetector([weak]), min_confidence=0.5)
    assert outcome.output["faces"] == 0 and written == []


async def test_detector_failure_fails_the_run_and_writes_nothing():
    """Fail closed: "no faces" is never reported for an image nobody inspected."""
    outcome, written = await run(FakeDetector(error=RuntimeError("cuda gone")))
    assert (outcome.status, outcome.code) == ("failed", "detection_failed")
    assert written == []


async def test_malformed_box_fails_the_run():
    outcome, written = await run(FakeDetector([Detection("face", float("nan"), 0, 5, 5, 0.9)]))
    assert (outcome.status, outcome.code) == ("failed", "detection_failed")
    assert written == []


async def test_missing_weights_fail_the_run_with_their_own_code():
    from sm_images.steps.anonymize.weights import WeightsUnavailable

    outcome, _ = await run(FakeDetector(error=WeightsUnavailable("no face.pt")))
    assert (outcome.status, outcome.code) == ("failed", "weights_unavailable")


async def test_an_undecodable_file_fails_the_run():
    outcome, _ = await run(FakeDetector([]), data=b"not an image")
    assert (outcome.status, outcome.code) == ("failed", "unreadable_image")


async def test_max_detection_dim_downscales_and_regions_scale_back(monkeypatch):
    from sm_images.steps.anonymize import step as step_mod

    monkeypatch.setattr(step_mod, "MAX_DETECTION_DIM", 32)

    def half_box(image: PILImage.Image) -> list[Detection]:
        w, h = image.size  # 32x24 for a 64x48 picture
        return [Detection("face", w / 4, h / 4, w / 2, h / 2, 0.9)]

    fake = FakeDetector(half_box)
    outcome, written = await run(fake, padding=0)
    assert fake.calls[0]["size"] == (32, 24)
    (region,) = outcome.output["regions"]
    assert (region["x"], region["y"], region["w"], region["h"]) == (16, 12, 32, 24)
    assert decode(written[0][0]).size == (64, 48)  # the display copy keeps full size


async def test_regions_are_on_the_exif_transposed_image():
    """Orientation 6 (rotate 90 CW): a 64x48 file shows as 48x64. The detector
    sees the upright picture and the display copy is upright, with no tag."""
    fake = FakeDetector([Detection("face", 0, 0, 10, 10, 0.9)])
    outcome, written = await run(fake, data=picture(exif_orientation=6), padding=0)
    assert fake.calls[0]["size"] == (48, 64)
    shown = PILImage.open(__import__("io").BytesIO(written[0][0]))
    assert shown.size == (48, 64)
    assert shown.getexif().get(0x0112) in (None, 1)
    assert outcome.output["regions"][0]["w"] == 10


def test_box_near_top_left_clamps_to_zero():
    assert pad_and_clamp(2, 3, 10, 10, 100, 100, 0.5) == (0, 0, 17, 18)


def test_box_near_bottom_right_clamps_to_image_edge():
    assert pad_and_clamp(90, 92, 10, 8, 100, 100, 0.5) == (85, 88, 15, 12)


def test_interior_box_grows_by_twice_the_padding():
    assert pad_and_clamp(40, 40, 20, 10, 100, 100, 0.25) == (35, 37, 30, 16)


@pytest.fixture
def clean():
    registry.reset_registry()
    yield
    registry.reset_registry()


def _specs(monkeypatch, present: set[str]) -> None:
    import importlib.util

    real = importlib.util.find_spec
    heavy = {"torch", "ultralytics"}

    def fake(name, *a):
        if name in heavy:
            return real("json") if name in present else None
        return real(name, *a)

    monkeypatch.setattr(importlib.util, "find_spec", fake)


def test_registered_when_the_extra_is_installed(clean, monkeypatch):
    _specs(monkeypatch, {"torch", "ultralytics"})
    extensions.load_extensions()
    step = registry.get_step("anonymize")
    assert step is not None
    assert (step.queue, step.mutates_display) == ("images_gpu", True)


@pytest.mark.parametrize("missing", ["torch", "ultralytics"])
def test_absent_without_the_extra(clean, monkeypatch, missing):
    _specs(monkeypatch, {"torch", "ultralytics"} - {missing})
    extensions.load_extensions()
    assert registry.get_step("anonymize") is None
    assert registry.get_step("renditions") is not None


def test_importing_the_step_pulls_no_heavy_module():
    import subprocess
    import sys

    code = (
        "import sys, sm_images.steps.anonymize, sm_images.steps.anonymize.step;"
        "print(sorted(m for m in ('torch','ultralytics','cv2') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
