"""NDJSON points -> a PMTiles archive, through tippecanoe (ported from the portal).

``B/pipeline/pmtiles.py`` and ``B/constants_pmtiles.py``: one feature per line,
coordinates finite and in range, then tippecanoe with the portal's exact
arguments as an argument list - never a shell - under a timeout that grows
with the point count. The binary is the ``tippecanoe_path`` setting (a bare
name is looked up on ``PATH``); :func:`locate` is also what the health check
asks.

``-r1`` turns off tippecanoe's default gamma drop-sampling so clustering sees
every point; clustering stops at z13 so the deepest zoom carries individual
points, co-located ones included; ``--drop-fraction-as-needed`` (not
``--drop-densest-as-needed``) is the safety net for a deepest-zoom tile still
over the size limit, and leaves co-located points alone unless it must.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final, TextIO

from sm_images.map.points import feature

__all__ = [
    "LAYER",
    "TippecanoeError",
    "convert",
    "locate",
    "timeout_for",
    "tippecanoe_args",
    "write_features",
]

logger = logging.getLogger(__name__)

LAYER: Final = "images"
MIN_ZOOM: Final = 0
MAX_ZOOM: Final = 14
CLUSTER_DISTANCE: Final = 10
"""Points closer than this (in 1/256ths of a tile) are clustered."""
CLUSTER_MAX_ZOOM: Final = 13
"""The last zoom that clusters; must stay below :data:`MAX_ZOOM`."""
LARGE_COLLECTION: Final = 100_000
"""From here on tippecanoe reads the (newline-delimited) input in parallel."""
BASE_TIMEOUT: Final = 120
TIMEOUT_PER_10K: Final = 30
MAX_TIMEOUT: Final = 3600
_STDERR_TAIL: Final = 2000


class TippecanoeError(RuntimeError):
    """tippecanoe failed, timed out or could not be started."""


def locate(path: str) -> str | None:
    """The executable *path* names, or ``None``: a path is checked as given, a
    bare name looked up on ``PATH``."""
    if not path:
        return None
    if os.sep in path:
        return path if Path(path).is_file() and os.access(path, os.X_OK) else None
    return shutil.which(path)


def timeout_for(count: int) -> int:
    """``min(120 + floor(count / 10000) * 30, 3600)`` seconds, as the portal."""
    return min(BASE_TIMEOUT + (count // 10_000) * TIMEOUT_PER_10K, MAX_TIMEOUT)


def tippecanoe_args(binary: str, source: Path, output: Path, count: int) -> list[str]:
    args = [
        binary,
        "-o",
        str(output),
        "-Z",
        str(MIN_ZOOM),
        "-z",
        str(MAX_ZOOM),
        "-l",
        LAYER,
        "--force",
        "-r1",
        f"--cluster-distance={CLUSTER_DISTANCE}",
        f"--cluster-maxzoom={CLUSTER_MAX_ZOOM}",
        "--cluster-densest-as-needed",
        "--drop-fraction-as-needed",
    ]
    if count >= LARGE_COLLECTION:
        args.append("--read-parallel")
    args.append(str(source))
    return args


def _valid(lat: Any, lng: Any) -> bool:
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    return math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180


def write_features(out: TextIO, rows: Iterable[Any]) -> int:
    """Append ``(id, lat, lng, captured_at, group_id)`` rows as NDJSON lines;
    returns how many were written (an invalid coordinate is skipped).
    ``json.dumps`` escapes every control character, so a line never breaks."""
    written = 0
    for image_id, lat, lng, captured_at, group_id in rows:
        if not _valid(lat, lng):
            continue
        point = feature(image_id, float(lat), float(lng), captured_at, group_id)
        out.write(json.dumps(point, ensure_ascii=True, separators=(",", ":")) + "\n")
        written += 1
    return written


def convert(binary: str, source: Path, output: Path, count: int) -> None:
    """Run tippecanoe; raises :class:`TippecanoeError` (with a bounded stderr
    tail in the log, never in the message) on failure or timeout."""
    timeout = timeout_for(count)
    try:
        subprocess.run(
            tippecanoe_args(binary, source, output, count),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TippecanoeError(f"tippecanoe timed out after {timeout}s") from exc
    except subprocess.CalledProcessError as exc:
        logger.error(
            "images.map.tippecanoe_failed exit=%s stderr=%s",
            exc.returncode,
            (exc.stderr or "")[-_STDERR_TAIL:],
        )
        raise TippecanoeError(f"tippecanoe exited with {exc.returncode}") from exc
    except OSError as exc:
        raise TippecanoeError("tippecanoe could not be started") from exc
