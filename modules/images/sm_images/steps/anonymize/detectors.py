"""What finds faces and plates: the :class:`Detector` protocol and the YOLO one.

The step depends on the protocol only, so a test (or a host with a detector
of its own) injects one; :class:`YoloDetector` is the default. It imports
ultralytics (and through it torch) inside its methods, never at module load:
``pip install simple_module_images`` without the ``[anonymize]`` extra still
imports this file.

Fail closed, from the portal's findings: a detector that is enabled but cannot
run - weights missing, a load or inference error, a malformed box - raises,
and the run fails. Returning ``[]`` would publish an uninspected picture as
anonymised.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from sm_images.steps.anonymize.weights import weights_file

if TYPE_CHECKING:
    from PIL import Image

__all__ = ["Detection", "Detector", "YoloDetector"]


@dataclass(frozen=True, slots=True)
class Detection:
    """One box in the coordinates of the image the detector was given."""

    kind: str  # "face" | "plate"
    x: float
    y: float
    w: float
    h: float
    score: float


@runtime_checkable
class Detector(Protocol):
    def detect(
        self, image: Image.Image, *, faces: bool, plates: bool, min_confidence: float
    ) -> list[Detection]:
        """Boxes of the enabled kinds in an upright RGB *image*. Raises when an
        enabled kind cannot be inspected; never answers ``[]`` for that."""
        ...


class YoloDetector:
    """ultralytics YOLO for both kinds, one model file each (see ``weights``).

    Models load lazily on first use and stay loaded for the process; the GPU is
    used when torch sees one.
    """

    def __init__(self, configured: str = "", *, cache_dir: Path | None = None) -> None:
        self.configured = configured
        self.cache_dir = cache_dir
        self._models: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _model(self, kind: str) -> Any:
        with self._lock:
            model = self._models.get(kind)
            if model is None:
                path = weights_file(kind, self.configured, cache_dir=self.cache_dir)
                from ultralytics import YOLO  # the [anonymize] extra

                model = self._models[kind] = YOLO(str(path))
            return model

    def _boxes(self, kind: str, image: Image.Image, conf: float) -> list[Detection]:
        out: list[Detection] = []
        for result in self._model(kind).predict(image, conf=conf, verbose=False):
            boxes = result.boxes
            if boxes is None:
                continue
            corners, scores = boxes.xyxy.tolist(), boxes.conf.tolist()
            for (x1, y1, x2, y2), score in zip(corners, scores, strict=True):
                out.append(Detection(kind, x1, y1, x2 - x1, y2 - y1, float(score)))
        return out

    def detect(
        self, image: Image.Image, *, faces: bool, plates: bool, min_confidence: float
    ) -> list[Detection]:
        found: list[Detection] = []
        if faces:
            found += self._boxes("face", image, min_confidence)
        if plates:
            found += self._boxes("plate", image, min_confidence)
        return found


_shared: dict[str, YoloDetector] = {}
_shared_lock = threading.Lock()


def shared_detector(configured: str) -> YoloDetector:
    """The process's detector for a weights setting: models load once per worker."""
    with _shared_lock:
        det = _shared.get(configured)
        if det is None:
            det = _shared[configured] = YoloDetector(configured)
        return det
