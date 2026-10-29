"""What finds faces and plates: the :class:`Detector` protocol and the ONNX one.

The step depends on the protocol only, so a test (or a host with a detector
of its own) injects one; :class:`OnnxDetector` is the default. It imports
onnxruntime (and numpy) inside its methods, never at module load:
``pip install simple_module_images`` without the ``[anonymize]`` extra still
imports this file.

Fail closed, from the portal's findings: a detector that is enabled but cannot
run - weights missing, a load or inference error, a malformed box - raises,
and the run fails. Returning ``[]`` would publish an uninspected picture as
anonymised.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from sm_images.steps.anonymize.models import detect_faces, detect_plates
from sm_images.steps.anonymize.weights import weights_bytes

if TYPE_CHECKING:
    from PIL import Image

__all__ = ["Detection", "Detector", "OnnxDetector"]


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


_PREFERRED_PROVIDERS = ("CUDAExecutionProvider", "CPUExecutionProvider")


class OnnxDetector:
    """YuNet for faces, YOLOv9 for plates, both on onnxruntime (see ``models``
    and ``weights``).

    Sessions load lazily on first use and stay loaded for the process; CUDA is
    used when the installed onnxruntime build offers it. A forked child (Celery's
    prefork pool) never uses its parent's sessions or lock: they are dropped
    and recreated in the child on first use.
    """

    def __init__(self, configured: str = "", *, cache_dir: Path | None = None) -> None:
        self.configured = configured
        self.cache_dir = cache_dir
        self._sessions: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._pid = os.getpid()

    def _session(self, kind: str) -> Any:
        if self._pid != os.getpid():  # forked: the parent's state is not ours
            self._lock = threading.Lock()
            self._sessions = {}
            self._pid = os.getpid()
        with self._lock:
            session = self._sessions.get(kind)
            if session is None:
                import onnxruntime as ort  # the [anonymize] extra

                data = weights_bytes(kind, self.configured, cache_dir=self.cache_dir)
                available = set(ort.get_available_providers())
                providers = [p for p in _PREFERRED_PROVIDERS if p in available]
                session = self._sessions[kind] = ort.InferenceSession(data, providers=providers)
            return session

    def _faces(self, image: Image.Image, conf: float) -> list[Detection]:
        session = self._session("face")
        names = [o.name for o in session.get_outputs()]
        feed = session.get_inputs()[0].name

        def run(tensor: Any) -> dict[str, Any]:
            return dict(zip(names, session.run(None, {feed: tensor}), strict=True))

        return [Detection("face", *box) for box in detect_faces(run, image, conf)]

    def _plates(self, image: Image.Image, conf: float) -> list[Detection]:
        session = self._session("plate")
        feed = session.get_inputs()[0].name
        boxes = detect_plates(lambda t: session.run(None, {feed: t}), image, conf)
        return [Detection("plate", *box) for box in boxes]

    def detect(
        self, image: Image.Image, *, faces: bool, plates: bool, min_confidence: float
    ) -> list[Detection]:
        found: list[Detection] = []
        if faces:
            found += self._faces(image, min_confidence)
        if plates:
            found += self._plates(image, min_confidence)
        return found


_shared: dict[str, OnnxDetector] = {}
_shared_lock = threading.Lock()


def shared_detector(configured: str) -> OnnxDetector:
    """The process's detector for a weights setting: models load once per worker."""
    with _shared_lock:
        det = _shared.get(configured)
        if det is None:
            det = _shared[configured] = OnnxDetector(configured)
        return det


def _after_fork_in_child() -> None:
    """A child starts with no detectors and an unheld lock, whatever another
    thread of the parent was doing at the fork."""
    global _shared, _shared_lock
    _shared = {}
    _shared_lock = threading.Lock()


os.register_at_fork(after_in_child=_after_fork_in_child)
