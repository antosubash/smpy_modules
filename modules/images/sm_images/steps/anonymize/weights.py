"""Where the detectors' weights come from. Never from the wheel.

* ``anonymize_weights_path`` set - a directory holding ``face.pt`` and
  ``plate.pt`` (ultralytics YOLO weights), used as they are: the operator
  chose them, so they are not checksummed against the defaults. A missing file
  fails the run (``weights_unavailable``) rather than skipping a detector.
* unset - the pinned files below are downloaded once into
  :func:`default_cache_dir` (``0700``, symlinks refused) and verified by size
  and SHA-256 on **every** load, never trusted by name: a ``.pt`` file is a
  pickle. The hash covers the very bytes the loader reads - they are read once,
  hashed, and written to a private ``0600`` snapshot in a fresh ``0700``
  directory, whose path is what YOLO gets; the snapshot is gone once loaded.
  So a cache file swapped after verification is never loaded. The URLs are
  constants, so this is a plain HTTPS fetch, not the import module's
  safe-fetch, which exists for URLs a user supplies.

Both defaults are AGPL-3.0 checkpoints from Hugging Face, pinned to a commit:
``arnabdhar/YOLOv8-Face-Detection`` (faces) and
``morsetechlab/yolov11-license-plate-detection`` (plates, the ``s`` size).
"""

from __future__ import annotations

import errno
import hashlib
import os
import shutil
import stat
import tempfile
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def weights_file(
    kind: str, configured: str = "", *, cache_dir: Path | None = None
) -> Iterator[Path]:
    """A path to load *kind*'s weights from, valid inside the ``with``.

    Configured: the operator's file, as is. Otherwise a private snapshot of the
    pinned bytes, verified this very call and removed on exit."""
    spec = WEIGHTS[kind]
    if configured:
        path = Path(configured).expanduser() / spec.filename
        if not path.is_file():
            raise WeightsUnavailable(f"{path} not found (anonymize_weights_path)")
        yield path
        return
    data = _verified_bytes(spec, cache_dir or default_cache_dir())
    snap_dir = Path(tempfile.mkdtemp(prefix="sm-images-weights-"))  # 0700, ours
    try:
        snap = snap_dir / spec.filename
        fd = os.open(snap, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        yield snap
    finally:
        shutil.rmtree(snap_dir, ignore_errors=True)
