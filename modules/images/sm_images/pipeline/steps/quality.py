"""The ``quality`` step: resolution, sharpness and exposure of the original.

Needs the ``[quality]`` extra (OpenCV). The core module imports without it: this
module imports nothing heavy at load, ``cv2`` only inside the CPU function, and
:func:`register_quality` registers the step only when ``cv2`` is installed. With
it absent a collection that enables ``quality`` keeps the configuration and the
run settles as ``not_installed`` (never scheduled).

* blur - variance of the Laplacian of the grey image (higher is sharper);
* exposure - histogram-weighted mean grey level in ``[0, 1]`` (0 black, 1 white);
* resolution - the oriented pixel size against the minimums.

Thresholds are inclusive and per collection (the step's params). ``passed`` is
informational: a photo that fails the checks is still a **completed** run, only
an unreadable file fails the run. The step reads the original, so a display
mutator (anonymisation) does not skew the sharpness.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sm_images.core.errors import ImageTooLarge
from sm_images.pipeline import registry
from sm_images.pipeline.step import StepContext, StepOutcome

__all__ = ["QualityParams", "QualityStep", "measure", "register_quality"]


class QualityParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_width: int = Field(640, ge=1, le=100_000)
    min_height: int = Field(480, ge=1, le=100_000)
    blur_threshold: float = Field(100.0, ge=0, allow_inf_nan=False)
    dark_threshold: float = Field(0.05, ge=0, le=1)
    bright_threshold: float = Field(0.95, ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> QualityParams:
        if self.dark_threshold > self.bright_threshold:
            raise ValueError("dark_threshold must not exceed bright_threshold")
        return self


def measure(data: bytes, p: QualityParams) -> dict[str, Any]:
    """The metrics and verdicts for ``data``. Raises on an undecodable file, and
    ``ImageTooLarge`` on a pixel bomb before anything is decoded."""
    import cv2  # the [quality] extra; deliberately not at module level
    import numpy as np
    from PIL import Image, ImageOps

    from sm_images.ingest.guards import guard_pixels
    from sm_images.pipeline.processing.heif import register_heif

    register_heif()
    guard_pixels(data)  # the decompression-bomb guard, before any decode
    with Image.open(io.BytesIO(data)) as src:
        src.load()
        img = ImageOps.exif_transpose(src)
        width, height = img.size
        gray = np.asarray(img.convert("L"))
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    exposure = float((hist / hist.sum() * np.arange(256)).sum() / 255.0)
    resolution_ok = width >= p.min_width and height >= p.min_height
    blur_ok = blur >= p.blur_threshold
    exposure_ok = p.dark_threshold <= exposure <= p.bright_threshold
    return {
        "width": width,
        "height": height,
        "blur_score": blur,
        "exposure_score": exposure,
        "resolution_ok": resolution_ok,
        "blur_ok": blur_ok,
        "exposure_ok": exposure_ok,
        "passed": resolution_ok and blur_ok and exposure_ok,
    }


class QualityStep:
    id = "quality"
    version = 1
    requires: tuple[str, ...] = ()
    mutates_display = False
    queue = "images_heavy"

    def params_schema(self) -> type[BaseModel]:
        return QualityParams

    def applies(self, image: Any, params: BaseModel) -> bool:
        return True

    async def run(self, ctx: StepContext) -> StepOutcome:
        params = ctx.params
        assert isinstance(params, QualityParams)
        data = await ctx.read_original()
        try:
            out = await asyncio.to_thread(measure, data, params)
        except ImageTooLarge as exc:
            return StepOutcome.failed("image_too_large", str(exc)[:500])
        except Exception as exc:  # PIL decode errors are many types; the file is the problem
            return StepOutcome.failed("unreadable_image", f"{type(exc).__name__}: {exc}"[:500])
        return StepOutcome.completed(out)


def register_quality() -> None:
    """A ``_BUILTIN_LOADERS`` entry: registers ``quality`` only if OpenCV is installed."""
    if importlib.util.find_spec("cv2") is not None:
        registry.register_builtin(QualityStep())
