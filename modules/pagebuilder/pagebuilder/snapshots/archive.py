"""Reading and writing a bundle as a ``.zip``.

An uploaded archive is attacker-controlled the moment someone can reach the
upload endpoint, so every entry is checked before anything touches disk: names
must stay inside the destination, the manifest must exist and declare a format
this build understands, and every blob must actually hash to the name it
arrived under.

Validation happens here, at the boundary, rather than during apply. A bundle
that is going to fail should fail while it is still a file someone can replace,
not halfway through overwriting a live site.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from pagebuilder.snapshots.assets import collect_sentinels
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.format import (
    BLOBS_DIR,
    FORMAT_VERSION,
    LAYOUT_NAME,
    MANIFEST_NAME,
    MEDIA_DIR,
    MEDIA_INDEX_NAME,
    PAGES_DIR,
    REDIRECTS_NAME,
)


class BundleError(Exception):
    """A bundle that cannot be trusted, with a reason fit to show a user."""


_BLOB_PREFIX = f"{MEDIA_DIR}/{BLOBS_DIR}/"

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _safe_relative(name: str) -> PurePosixPath:
    """Reject any entry that would write outside the destination."""
    candidate = PurePosixPath(name)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise BundleError(f"unsafe path in bundle: {name}")
    # A Windows-style absolute path survives PurePosixPath intact.
    if len(name) > 1 and name[1] == ":":
        raise BundleError(f"unsafe path in bundle: {name}")
    # An empty name or "." normalises to the destination directory itself —
    # not a traversal, but `dest / candidate` would then *be* a directory,
    # and writing bytes to it raises IsADirectoryError instead of the clean
    # rejection every other malformed entry gets.
    if not name or candidate == PurePosixPath("."):
        raise BundleError(f"unsafe path in bundle: {name!r}")
    return candidate


def _require_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BundleError("manifest.json is not an object")
    version = payload.get("format_version")
    if version != FORMAT_VERSION:
        raise BundleError(
            f"unsupported bundle format version {version!r}; "
            f"this build reads version {FORMAT_VERSION}"
        )
    return payload


def _check_sentinels(dest: Path, index: dict[str, Any]) -> None:
    """Every ``asset://`` reference must name an entry in the media index."""
    referenced: set[str] = set()
    for document in sorted((dest / PAGES_DIR).glob("*.json")):
        referenced |= collect_sentinels(json.loads(document.read_text()))
    layout = dest / LAYOUT_NAME
    if layout.is_file():
        referenced |= collect_sentinels(json.loads(layout.read_text()))

    missing = sorted(referenced - set(index))
    if missing:
        raise BundleError(
            "bundle references media it does not contain: " + ", ".join(missing)
        )


def write_zip(
    bundle_dir: Path,
    blobs: BlobStore,
    media: list[dict[str, Any]],
    target: Path,
) -> int:
    """Zip a server-side bundle together with the blobs it references."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(bundle_dir).as_posix())
        for row in media:
            sha256 = row["sha256"]
            if blobs.exists(sha256):
                archive.writestr(f"{_BLOB_PREFIX}{sha256}", blobs.get(sha256))
    return target.stat().st_size


def read_zip(
    data: bytes, dest: Path, blobs: BlobStore
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract, validate and store *data*. Returns ``(manifest, media index)``.

    Documents land in *dest*; blob bytes go straight into the shared store, so
    the extracted tree holds only JSON regardless of how large the media was.
    """
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BundleError("not a readable zip archive") from exc

    dest.mkdir(parents=True, exist_ok=True)
    stored: dict[str, bytes] = {}

    with archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            relative = _safe_relative(name)
            payload = archive.read(name)
            if name.startswith(_BLOB_PREFIX):
                expected = relative.name
                actual = hashlib.sha256(payload).hexdigest()
                if actual != expected:
                    raise BundleError(f"blob {expected} does not match its contents")
                stored[expected] = payload
                continue
            out = dest / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)

    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BundleError("bundle has no manifest.json")
    manifest = _require_manifest(json.loads(manifest_path.read_text()))

    index_path = dest / MEDIA_DIR / MEDIA_INDEX_NAME
    index = json.loads(index_path.read_text()) if index_path.is_file() else {}
    if not isinstance(index, dict):
        raise BundleError("media/index.json is not an object")

    # Digests are checked before they are used as names. They arrive as JSON
    # strings inside the bundle, not as archive members, so `_safe_relative`
    # never saw them — and `BlobStore` joins them onto the store root.
    for name, entry in sorted(index.items()):
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(digest, str) or not _DIGEST.match(digest):
            raise BundleError(f"media entry {name!r} has no valid sha256: {digest!r}")

    missing_blobs = sorted(
        name
        for name, entry in index.items()
        if entry["sha256"] not in stored and not blobs.exists(entry["sha256"])
    )
    if missing_blobs:
        raise BundleError(
            "bundle is missing the bytes for: " + ", ".join(missing_blobs)
        )

    _check_sentinels(dest, index)

    # Only commit blobs once every check has passed, so a rejected bundle
    # leaves no trace in the shared store.
    for payload in stored.values():
        blobs.put(payload)

    if not (dest / REDIRECTS_NAME).is_file():
        (dest / REDIRECTS_NAME).write_text("[]\n")

    return manifest, index
