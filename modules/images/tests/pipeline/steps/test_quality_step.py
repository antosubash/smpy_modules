"""The ``quality`` step: metrics on a known fixture, and its cv2 gating."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageFilter
from sm_images.pipeline import extensions, registry
from sm_images.pipeline.step import StepContext

cv2 = pytest.importorskip("cv2")


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def checkerboard(w: int = 800, h: int = 600, cell: int = 8) -> Image.Image:
    img = Image.new("L", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = 255 if ((x // cell) + (y // cell)) % 2 else 0
    return img


SHARP = _png(checkerboard())
BLURRED = _png(checkerboard().filter(ImageFilter.GaussianBlur(6)))
DARK = _png(Image.new("RGB", (800, 600), (3, 3, 3)))
BRIGHT = _png(Image.new("RGB", (800, 600), (253, 253, 253)))


async def run_quality(data: bytes, **params):
    from sm_images.pipeline.steps.quality import QualityParams, QualityStep

    step = QualityStep()

    async def original() -> bytes:
        return data

    ctx = StepContext(
        step=step,
        image=SimpleNamespace(),
        params=QualityParams(**params),
        tenant_id="default",
        read_display=original,
        read_original=original,
    )
    return await step.run(ctx)


async def test_quality_metrics_known_fixture():
    sharp = (await run_quality(SHARP)).output
    blur = (await run_quality(BLURRED)).output
    assert (sharp["width"], sharp["height"]) == (800, 600)
    assert sharp["blur_score"] > 1000 > 100 > blur["blur_score"]
    assert 0.45 < sharp["exposure_score"] < 0.55  # half black, half white
    assert sharp["passed"] is True
    assert (blur["blur_ok"], blur["passed"]) == (False, False)
    assert blur["resolution_ok"] and blur["exposure_ok"]


async def test_exposure_and_resolution_flags():
    dark = (await run_quality(DARK)).output
    bright = (await run_quality(BRIGHT)).output
    assert (dark["exposure_ok"], bright["exposure_ok"]) == (False, False)
    assert dark["exposure_score"] < 0.05 < 0.95 < bright["exposure_score"]
    small = (await run_quality(SHARP, min_width=801)).output
    assert (small["resolution_ok"], small["passed"]) == (False, False)


async def test_thresholds_are_inclusive_and_a_failed_check_is_still_a_completed_run():
    sharp = (await run_quality(SHARP)).output
    got = await run_quality(SHARP, blur_threshold=sharp["blur_score"])
    assert got.status == "completed" and got.output["blur_ok"] is True
    low = await run_quality(BLURRED)  # fails the check, not the step
    assert low.status == "completed" and low.output["passed"] is False


async def test_an_undecodable_file_fails_the_run_with_a_code():
    got = await run_quality(b"not an image")
    assert (got.status, got.code) == ("failed", "unreadable_image")


@pytest.mark.parametrize("side", [12, 20], ids=["1x-2x-warning-band", "over-2x"])
async def test_a_pixel_bomb_is_refused_before_decoding(monkeypatch, side):
    """``measure`` runs ``guard_pixels`` first: Pillow alone only *warns* in the
    1x-2x band and would decode the whole bitmap."""
    from sm_images.core.errors import ImageTooLarge
    from sm_images.pipeline.steps.quality import QualityParams, measure

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    bomb = _png(Image.new("RGB", (side, side), (128, 128, 128)))
    with pytest.raises(ImageTooLarge):
        measure(bomb, QualityParams())
    got = await run_quality(bomb)
    assert (got.status, got.code) == ("failed", "image_too_large")


def test_params_are_validated():
    from sm_images.pipeline.steps.quality import QualityParams

    assert QualityParams().model_dump() == {
        "min_width": 640,
        "min_height": 480,
        "blur_threshold": 100.0,
        "dark_threshold": 0.05,
        "bright_threshold": 0.95,
    }
    for bad in ({"min_width": 0}, {"blur_threshold": -1}, {"dark_threshold": 0.97}, {"nope": 1}):
        with pytest.raises(ValueError):
            QualityParams(**bad)


@pytest.fixture
def clean():
    registry.reset_registry()
    yield
    registry.reset_registry()


def test_quality_registered_with_cv2(clean):
    extensions.load_extensions()
    step = registry.get_step("quality")
    assert step is not None and step.queue == "images_heavy" and step.mutates_display is False


def test_quality_absent_without_cv2(clean, monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a: None if name == "cv2" else real(name, *a)
    )
    extensions.load_extensions()
    assert registry.get_step("quality") is None
    assert registry.get_step("exif") is not None
