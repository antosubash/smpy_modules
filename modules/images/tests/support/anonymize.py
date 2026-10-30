"""A fake detector for the ``anonymize`` step, and a registry that runs it.

The real detectors need the ``[anonymize]`` extra (onnxruntime) and
weights, which default CI never installs; every unit test injects this fake.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

from PIL import Image as PILImage
from sm_images.pipeline import registry
from sm_images.pipeline.builtin_steps import register_builtins
from sm_images.steps.anonymize import AnonymizeStep, Detection

Found = list[Detection] | Callable[[PILImage.Image], list[Detection]]


class FakeDetector:
    """Answers with ``found`` (or ``found(image)``), honouring the kind toggles
    the step passes - like a real detector, which never runs a disabled model."""

    def __init__(self, found: Found = (), *, error: Exception | None = None) -> None:
        self.found = found
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def detect(
        self, image: PILImage.Image, *, faces: bool, plates: bool, min_confidence: float
    ) -> list[Detection]:
        self.calls.append(
            {"size": image.size, "faces": faces, "plates": plates, "conf": min_confidence}
        )
        if self.error is not None:
            raise self.error
        got = self.found(image) if callable(self.found) else list(self.found)
        wanted = {"face"} if faces else set()
        if plates:
            wanted.add("plate")
        return [d for d in got if d.kind in wanted]


def use_anonymize(detector: FakeDetector, *extra: Any) -> None:
    """Built-ins plus ``anonymize`` (a reserved id) on the fake, then frozen."""
    registry.reset_registry()
    register_builtins()
    registry.register_builtin(AnonymizeStep(detector=detector))
    for step in extra:
        registry.register_step(step)
    registry.freeze()


def picture(size: tuple[int, int] = (64, 48), *, exif_orientation: int | None = None) -> bytes:
    """A red JPEG with a black-and-white checkered square in the middle: the
    "face" to hide (detail a blur must destroy)."""
    w, h = size
    img = PILImage.new("RGB", size, (200, 20, 20))
    px = img.load()
    for y in range(h // 2 - h // 8, h // 2 + h // 8):
        for x in range(w // 2 - w // 8, w // 2 + w // 8):
            px[x, y] = (255, 255, 255) if (x // 2 + y // 2) % 2 else (0, 0, 0)
    buf = io.BytesIO()
    if exif_orientation is None:
        img.save(buf, format="JPEG", quality=95)
    else:
        exif = PILImage.Exif()
        exif[0x0112] = exif_orientation
        img.save(buf, format="JPEG", quality=95, exif=exif.tobytes())
    return buf.getvalue()


def decode(data: bytes) -> PILImage.Image:
    with PILImage.open(io.BytesIO(data)) as img:
        img.load()
        return img.convert("RGB")
