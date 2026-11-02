"""The ``anonymize`` step: blur faces and number plates into a display copy.

The first built-in display mutator (spec §3). It reads the **original** - a
re-run starts from the unblurred picture, never from its own earlier output -
upright (EXIF-transposed), finds the enabled kinds on a copy scaled down to
:data:`MAX_DETECTION_DIM`, pads each box, obscures it at full size and hands
the JPEG to ``ctx.write_display``. ``storage_key`` is never touched: the
executor publishes the copy under the run's lease, and serving keeps the
original behind the owner and ``images.originals.view``.

* nothing found - ``completed`` with no display copy: the original is already
  safe to show, and re-encoding it would only cost quality;
* faces and plates both off - ``skipped`` (``nothing_to_detect``), a skip the
  step itself returns, so the redaction gate counts it as settled;
* a detector that cannot run, or a malformed box - ``failed``: never "no faces"
  for a picture nobody inspected.

Output ``{regions: [{kind, x, y, w, h, score}], faces, plates}``, in the
display copy's pixels. Region coordinates are visible to editors only
(``present_detail``'s ``output_visible``).

Needs the ``[anonymize]`` extra (onnxruntime, which brings numpy);
:func:`register_anonymize` registers the step only when both are importable.
"""

from __future__ import annotations

import asyncio
import importlib
import io
import logging
import math
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from sm_images.core.errors import ImageTooLarge
from sm_images.pipeline import registry
from sm_images.pipeline.step import StepContext, StepOutcome
from sm_images.pipeline.steps.anonymize.blur import Region, blur_regions, pad_and_clamp
from sm_images.pipeline.steps.anonymize.detectors import Detection, Detector
from sm_images.pipeline.steps.anonymize.weights import WeightsUnavailable

__all__ = ["MAX_DETECTION_DIM", "AnonymizeParams", "AnonymizeStep", "register_anonymize"]

logger = logging.getLogger(__name__)

MAX_DETECTION_DIM: Final = 1600
"""The detector sees the picture scaled to at most this many pixels a side."""
JPEG_QUALITY: Final = 90
MAX_REPORTED: Final = 200
"""Regions listed in the output; every one found is blurred and counted."""
EXTRA_MODULES: Final = ("onnxruntime", "numpy")


class AnonymizeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    faces: bool = True
    plates: bool = True
    padding: float = Field(0.15, ge=0, le=1)
    """Each box grows by this fraction of its own size on every side."""
    min_confidence: float = Field(0.5, ge=0, le=1)


def load_upright(data: bytes) -> Any:
    """The picture as displayed: decompression-bomb guard, EXIF transpose, RGB."""
    from PIL import Image, ImageOps

    from sm_images.ingest.guards import guard_pixels
    from sm_images.pipeline.processing.heif import register_heif

    register_heif()
    guard_pixels(data)
    with Image.open(io.BytesIO(data)) as src:
        src.load()
        img = ImageOps.exif_transpose(src)
    if img.mode in ("RGBA", "LA", "PA", "P") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return img.convert("RGB")


def find_regions(img: Any, p: AnonymizeParams, detector: Detector) -> list[Region]:
    """Detect on a scaled copy, then map each box back to *img*, padded."""
    from PIL import Image

    width, height = img.size
    scale = min(1.0, MAX_DETECTION_DIM / max(width, height))
    probe = img
    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        probe = img.resize(size, Image.Resampling.LANCZOS)
    sx, sy = width / probe.size[0], height / probe.size[1]
    wanted = {k for k, on in (("face", p.faces), ("plate", p.plates)) if on}
    found = detector.detect(probe, faces=p.faces, plates=p.plates, min_confidence=p.min_confidence)
    regions = []
    for d in found:
        _check(d, p.min_confidence)
        if d.kind not in wanted or d.score < p.min_confidence:
            continue
        x, y, w, h = d.x * sx, d.y * sy, d.w * sx, d.h * sy
        # Confident, so it must show on the picture: a box that lies wholly off
        # it once mapped back is a broken detector, never "nothing to blur".
        if min(x + w, width) <= max(x, 0) or min(y + h, height) <= max(y, 0):
            raise ValueError(f"confident {d.kind} box off the picture: {d!r}")
        box = pad_and_clamp(x, y, w, h, width, height, p.padding)
        regions.append(Region(d.kind, *box, score=float(d.score)))
    return regions


def _check(d: Detection, min_confidence: float) -> None:
    """Non-finite or negative is malformed at any score; an empty box only when
    confident (one that would be blurred, had it an area)."""
    values = (d.x, d.y, d.w, d.h, d.score)
    if d.kind not in ("face", "plate") or not all(math.isfinite(float(v)) for v in values):
        raise ValueError(f"malformed detection {d!r}")
    if d.w < 0 or d.h < 0 or (d.score >= min_confidence and (d.w == 0 or d.h == 0)):
        raise ValueError(f"malformed detection {d!r}")


def render(img: Any, regions: list[Region]) -> bytes:
    """The blurred display copy as a JPEG, with no metadata (the EXIF stays
    with the original; the copy is already upright)."""
    buf = io.BytesIO()
    blur_regions(img, regions).save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _output(regions: list[Region]) -> dict[str, Any]:
    return {
        "regions": [r.as_output() for r in regions[:MAX_REPORTED]],
        "faces": sum(r.kind == "face" for r in regions),
        "plates": sum(r.kind == "plate" for r in regions),
    }


def _default_detector(ctx: StepContext) -> Detector:
    from sm_images.pipeline.steps.anonymize.detectors import shared_detector

    settings = getattr(getattr(ctx, "_staging", None), "settings", None)
    return shared_detector(str(getattr(settings, "anonymize_weights_path", "") or ""))


class AnonymizeStep:
    id = "anonymize"
    version = 1
    requires: tuple[str, ...] = ()
    mutates_display = True
    queue = "images_gpu"

    def __init__(self, detector: Detector | None = None) -> None:
        self._detector = detector

    def params_schema(self) -> type[BaseModel]:
        return AnonymizeParams

    def applies(self, image: Any, params: BaseModel) -> bool:
        return True

    async def run(self, ctx: StepContext) -> StepOutcome:
        p = ctx.params
        assert isinstance(p, AnonymizeParams)
        if not (p.faces or p.plates):
            return StepOutcome.skipped("nothing_to_detect")
        data = await ctx.read_original()
        try:
            img = await asyncio.to_thread(load_upright, data)
        except ImageTooLarge as exc:
            return StepOutcome.failed("image_too_large", str(exc)[:500])
        except Exception as exc:  # PIL decode errors are many types; the file is the problem
            return StepOutcome.failed("unreadable_image", f"{type(exc).__name__}: {exc}"[:500])
        await ctx.progress(10)
        detector = self._detector or _default_detector(ctx)
        try:
            regions = await asyncio.to_thread(find_regions, img, p, detector)
        except WeightsUnavailable as exc:
            return StepOutcome.failed("weights_unavailable", str(exc)[:500])
        except Exception as exc:  # fail closed: an uninspected picture is never "clean"
            return StepOutcome.failed("detection_failed", f"{type(exc).__name__}: {exc}"[:500])
        await ctx.progress(80)
        if regions:
            await ctx.write_display(await asyncio.to_thread(render, img, regions), "image/jpeg")
        return StepOutcome.completed(_output(regions))


def register_anonymize() -> None:
    """A ``_BUILTIN_LOADERS`` entry: registers ``anonymize`` only when the
    ``[anonymize]`` extra (onnxruntime, numpy) is installed **and imports**: a
    broken native build (a missing shared library) leaves the step unregistered
    rather than failing every run."""
    for name in EXTRA_MODULES:
        try:
            importlib.import_module(name)
        except (ImportError, OSError) as exc:
            logger.warning("anonymize step not registered: %s does not import (%s)", name, exc)
            return
    registry.register_builtin(AnonymizeStep())
