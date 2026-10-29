"""Where the detectors' weights come from. Never from the wheel.

* ``anonymize_weights_path`` set - a directory holding ``face.pt`` and
  ``plate.pt`` (ultralytics YOLO weights), used as they are: the operator
  chose them, so they are not checksummed against the defaults. A missing file
  fails the run (``weights_unavailable``) rather than skipping a detector.
* unset - the pinned files below are downloaded once into
  :func:`default_cache_dir` and verified by size and SHA-256 before anything
  loads them (a ``.pt`` file is a pickle). The URLs are constants, so this is
  a plain HTTPS fetch, not the import module's safe-fetch, which exists for
  URLs a user supplies.

Both defaults are AGPL-3.0 checkpoints from Hugging Face, pinned to a commit:
``arnabdhar/YOLOv8-Face-Detection`` (faces) and
``morsetechlab/yolov11-license-plate-detection`` (plates, the ``s`` size).
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

__all__ = [
    "WEIGHTS",
    "WeightsSpec",
    "WeightsUnavailable",
    "default_cache_dir",
    "weights_file",
]

_HF = "https://huggingface.co"
_TIMEOUT = httpx.Timeout(30.0, read=120.0)
_CHUNK = 1 << 20


class WeightsUnavailable(RuntimeError):  # noqa: N818 - the run's error code names it
    """A detector's weights cannot be had: the run fails, nothing is skipped."""


@dataclass(frozen=True, slots=True)
class WeightsSpec:
    kind: str
    filename: str
    url: str
    sha256: str
    size: int


WEIGHTS: dict[str, WeightsSpec] = {
    "face": WeightsSpec(
        kind="face",
        filename="face.pt",
        url=f"{_HF}/arnabdhar/YOLOv8-Face-Detection/resolve/"
        "52fa54977207fa4f021de949b515fb19dcab4488/model.pt",
        sha256="37396ac6a9601ab9f5177e4231b09d81cf6f65a7f22db99ec3b36ab63f674e71",
        size=6_247_065,
    ),
    "plate": WeightsSpec(
        kind="plate",
        filename="plate.pt",
        url=f"{_HF}/morsetechlab/yolov11-license-plate-detection/resolve/"
        "251a30d7daedca065f56e04b0af04052c907c68f/license-plate-finetune-v1s.pt",
        sha256="95e50c25ab7066dd0ca5aec18fa80349676db08697780d1149576461174d2381",
        size=19_173_715,
    ),
}

_lock = threading.Lock()
_verified: set[Path] = set()
"""Cache files already checksummed by this process."""


def default_cache_dir() -> Path:
    """The worker's own cache: ``~/.cache/simple_module_images/models``."""
    return Path.home() / ".cache" / "simple_module_images" / "models"


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True)


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _intact(path: Path, spec: WeightsSpec) -> bool:
    return path.is_file() and path.stat().st_size == spec.size and _digest(path) == spec.sha256


def _download(spec: WeightsSpec, dest: Path) -> None:
    """Fetch into a temporary file beside *dest*, verify, then rename into place
    (atomic, so a concurrent worker sees the whole file or none)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.part")
    h, got = hashlib.sha256(), 0
    try:
        with _client() as client, client.stream("GET", spec.url) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in resp.iter_bytes(_CHUNK):
                    got += len(chunk)
                    if got > spec.size:
                        raise WeightsUnavailable(f"{spec.filename}: larger than pinned")
                    h.update(chunk)
                    fh.write(chunk)
        if got != spec.size or h.hexdigest() != spec.sha256:
            raise WeightsUnavailable(f"{spec.filename}: checksum mismatch, refusing to load")
        tmp.replace(dest)
    except WeightsUnavailable:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise WeightsUnavailable(f"{spec.filename}: download failed ({exc})") from exc
    finally:
        tmp.unlink(missing_ok=True)


def weights_file(kind: str, configured: str = "", *, cache_dir: Path | None = None) -> Path:
    """The local path of *kind*'s weights, downloading the pinned file if needed."""
    spec = WEIGHTS[kind]
    if configured:
        path = Path(configured).expanduser() / spec.filename
        if not path.is_file():
            raise WeightsUnavailable(f"{path} not found (anonymize_weights_path)")
        return path
    path = (cache_dir or default_cache_dir()) / spec.filename
    with _lock:
        if path in _verified and path.is_file():
            return path
        if not _intact(path, spec):
            _download(spec, path)
        _verified.add(path)
    return path
