"""Refuse to publish over files PyPI already has with different contents.

    python3 scripts/release_pypi_check.py <distribution> <version> <dir>

release.yml publishes with ``skip-existing``, so re-running a half-finished
upload (the wheel accepted, the sdist not, or the response lost) skips what
PyPI already holds instead of failing on it and stranding the version. That
skip is by filename only; this check, run just before, makes it safe: every
local file PyPI already has must carry the same sha256, or the job fails
rather than leave PyPI serving something other than what was built.

Exits 0 when the version is not on PyPI yet or every overlapping file
matches, 1 on a mismatch or when PyPI cannot be asked (fail closed: the job
is re-run). The JSON API is CDN-cached, so a file uploaded seconds ago may
not show yet; in this workflow a retry uploads the same artifact the first
attempt did, so a stale answer can only skip a file that is identical
anyway. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

INDEX = "https://pypi.org/pypi"
ATTEMPTS = 3


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare(local: dict[str, str], released: list[dict]) -> tuple[list[str], list[str]]:
    """``(already uploaded and identical, uploaded with different contents)``.

    ``local`` maps filename to sha256; ``released`` is the ``urls`` list of
    PyPI's JSON API for the version.
    """
    remote = {f["filename"]: f.get("digests", {}).get("sha256") for f in released}
    same, differ = [], []
    for name, digest in sorted(local.items()):
        if name not in remote:
            continue
        (same if remote[name] == digest else differ).append(name)
    return same, differ


def fetch_released(distribution: str, version: str) -> list[dict]:
    """The version's files on PyPI; empty when it has none yet."""
    url = f"{INDEX}/{distribution}/{version}/json"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.load(response).get("urls", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            error: Exception = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        print(f"::warning::PyPI lookup failed (attempt {attempt}/{ATTEMPTS}): {error}")
        if attempt < ATTEMPTS:
            time.sleep(5 * attempt)
    raise SystemExit(f"::error::could not read {url}; re-run this job")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: release_pypi_check.py <distribution> <version> <dir>", file=sys.stderr)
        return 1
    distribution, version, directory = argv[1:]
    local = {p.name: sha256(p) for p in Path(directory).iterdir() if p.is_file()}
    same, differ = compare(local, fetch_released(distribution, version))
    for name in same:
        print(f"already on PyPI, identical, will be skipped: {name}")
    for name in differ:
        print(f"::error::{name} is on PyPI with a different sha256 than this build")
    if differ:
        print(
            f"::error::{distribution} {version} on PyPI was not built by this run;"
            " release the next version instead (docs/releasing.md)"
        )
        return 1
    if not same:
        print(f"{distribution} {version}: nothing on PyPI yet")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
