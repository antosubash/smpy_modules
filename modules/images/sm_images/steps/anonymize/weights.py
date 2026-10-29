"""Where the detectors' weights come from. Never from the wheel.

* ``anonymize_weights_path`` set - a directory holding ``face.onnx`` (a
  YuNet-compatible face model) and ``plate.onnx`` (an end-to-end YOLOv9 plate
  model with the open-image-models layout), used as they are: the operator
  chose them, so they are not checksummed against the defaults. A missing file
  fails the run (``weights_unavailable``) rather than skipping a detector.
* unset - the pinned files below are downloaded once into
  :func:`default_cache_dir` (``0700``, symlinks refused) and verified by size
  and SHA-256 on **every** load, never trusted by name. The hash covers the
  very bytes the runtime loads: they are read once, hashed, and handed to
  onnxruntime as bytes, so a cache file swapped after verification is never
  loaded. The URLs are constants, so this is a plain HTTPS fetch, not the
  import module's safe-fetch, which exists for URLs a user supplies.

The defaults (licences and attribution in ``docs/index.md`` and ``NOTICE``):

* faces - YuNet ``face_detection_yunet_2026may.onnx`` from OpenCV Zoo, MIT
  (Shiqi Yu), pinned to an opencv_zoo commit;
* plates - ``yolo-v9-s-608-license-plates-end2end.onnx`` from
  ankandrew/open-image-models, MIT, a release asset (the release is not
  immutable, so the SHA-256 is what pins it: a replaced file fails closed).
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
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
    "weights_bytes",
]

_ZOO = (
    "https://github.com/opencv/opencv_zoo/raw/eb9f4f2d4b79b58e5513b5d25d5f0243a8357bf4"
    "/models/face_detection_yunet"
)
_OIM = "https://github.com/ankandrew/open-image-models/releases/download/assets"
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
        filename="face.onnx",
        url=f"{_ZOO}/face_detection_yunet_2026may.onnx",
        sha256="ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
        size=229_738,
    ),
    "plate": WeightsSpec(
        kind="plate",
        filename="plate.onnx",
        url=f"{_OIM}/yolo-v9-s-608-license-plates-end2end.onnx",
        sha256="2b878b38d9aa07b6ddc3ea75c4ffcb39869bc5c218e0a14002f60ab2f7b0be9a",
        size=28_612_350,
    ),
}

_lock = threading.Lock()


def default_cache_dir() -> Path:
    """The worker's own cache: ``~/.cache/simple_module_images/models``."""
    return Path.home() / ".cache" / "simple_module_images" / "models"


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True)


def _matches(data: bytes, spec: WeightsSpec) -> bool:
    return len(data) == spec.size and hashlib.sha256(data).hexdigest() == spec.sha256


def _private_dir(d: Path) -> Path:
    """The cache directory: created ``0700``, never a symlink, ours, tightened."""
    d.mkdir(parents=True, mode=0o700, exist_ok=True)
    st = os.lstat(d)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise WeightsUnavailable(f"{d}: weights cache is a symlink or not a directory")
    if st.st_uid != os.getuid():
        raise WeightsUnavailable(f"{d}: weights cache is not owned by this process's user")
    if stat.S_IMODE(st.st_mode) != 0o700:
        d.chmod(0o700)
    return d


def _read_cached(path: Path, spec: WeightsSpec) -> bytes | None:
    """The cached file's bytes (at most one more than pinned), or ``None``."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise WeightsUnavailable(f"{path}: refusing a symlink in the weights cache") from exc
        raise WeightsUnavailable(f"{path}: unreadable ({exc})") from exc
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise WeightsUnavailable(f"{path}: not a regular file")
        return fh.read(spec.size + 1)


def _download(spec: WeightsSpec, dest: Path) -> bytes:
    """Fetch into a temporary ``0600`` file beside *dest*, verify, rename into
    place (atomic: a concurrent worker sees the whole file or none). Returns the
    verified bytes, so the caller loads exactly what was checked."""
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.part")
    buf = bytearray()
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with (
            os.fdopen(fd, "wb") as fh,
            _client() as client,
            client.stream("GET", spec.url) as resp,
        ):
            resp.raise_for_status()
            for chunk in resp.iter_bytes(_CHUNK):
                if len(buf) + len(chunk) > spec.size:
                    raise WeightsUnavailable(f"{spec.filename}: larger than pinned")
                buf += chunk
                fh.write(chunk)
        data = bytes(buf)
        if not _matches(data, spec):
            raise WeightsUnavailable(f"{spec.filename}: checksum mismatch, refusing to load")
        tmp.replace(dest)
        return data
    except WeightsUnavailable:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise WeightsUnavailable(f"{spec.filename}: download failed ({exc})") from exc
    finally:
        tmp.unlink(missing_ok=True)


def _verified_bytes(spec: WeightsSpec, cache_dir: Path) -> bytes:
    with _lock:
        path = _private_dir(cache_dir) / spec.filename
        data = _read_cached(path, spec)
        if data is not None and _matches(data, spec):
            return data
        return _download(spec, path)


def weights_bytes(kind: str, configured: str = "", *, cache_dir: Path | None = None) -> bytes:
    """*kind*'s model, as the bytes onnxruntime loads.

    Configured: the operator's file, as is. Otherwise the pinned bytes,
    verified this very call."""
    spec = WEIGHTS[kind]
    if configured:
        path = Path(configured).expanduser() / spec.filename
        try:
            return path.read_bytes()
        except OSError as exc:
            raise WeightsUnavailable(f"{path} not found (anonymize_weights_path)") from exc
    return _verified_bytes(spec, cache_dir or default_cache_dir())
