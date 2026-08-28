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
import shutil
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from pagebuilder.models import PageStatus
from pagebuilder.snapshots.assets import collect_sentinels
from pagebuilder.snapshots.blobs import BlobStore, is_digest
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


def _load(path: Path, label: str) -> Any:
    """Parse a bundle document, reporting bad JSON as a bundle problem.

    ``json.JSONDecodeError`` is a ``ValueError``, not a ``BundleError``, so
    without this every malformed document escaped the boundary as a 500 and
    skipped the caller's cleanup of the half-extracted directory.
    """
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise BundleError(f"{label} is not valid JSON") from exc


def _check_page(label: str, payload: Any) -> None:
    """Reject a page document ``apply_payload`` would choke on.

    Schema checks belong here with the rest of the boundary, not at apply
    time: by then a pre-restore snapshot has been taken and pages are being
    written, so an unknown status would surface as a 500 halfway through a
    restore rather than as a rejection of the file that caused it.
    """
    if not isinstance(payload, dict):
        raise BundleError(f"{label} is not an object")
    slug = payload.get("slug")
    if not isinstance(slug, str) or not slug:
        raise BundleError(f"{label} has no slug")
    status = payload.get("status")
    try:
        PageStatus(status)
    except ValueError as exc:
        raise BundleError(f"{label} has an unknown status: {status!r}") from exc
    for field in ("publish_at", "unpublish_at"):
        raw = payload.get(field)
        if not raw:
            continue
        try:
            datetime.fromisoformat(raw)
        except (TypeError, ValueError) as exc:
            raise BundleError(f"{label} has an unreadable {field}: {raw!r}") from exc


def _check_documents(dest: Path, index: dict[str, Any]) -> None:
    """Validate every page and layout document, in one pass over the tree.

    Each document is parsed once and both checked for shape and scanned for
    ``asset://`` references, so the two concerns cannot drift apart over which
    files they consider a document.
    """
    referenced: set[str] = set()
    for document in sorted((dest / PAGES_DIR).glob("*.json")):
        label = f"{PAGES_DIR}/{document.name}"
        payload = _load(document, label)
        _check_page(label, payload)
        referenced |= collect_sentinels(payload)
    layout = dest / LAYOUT_NAME
    if layout.is_file():
        referenced |= collect_sentinels(_load(layout, LAYOUT_NAME))

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
            # Loudly, not silently: the media index travels in the bundle and
            # names this digest, so skipping it would produce a zip that looks
            # fine at download and is rejected by `read_zip`'s missing-bytes
            # check on whatever host tries to import it.
            if not blobs.exists(sha256):
                raise BundleError(f"snapshot is missing the bytes for {sha256}")
            # Streamed from the store rather than read into memory: a media
            # library of hundreds of megabytes would otherwise be materialised
            # one blob at a time on top of the zip being written.
            archive.write(blobs.path_for(sha256), f"{_BLOB_PREFIX}{sha256}")
    return target.stat().st_size


def read_zip(
    data: bytes,
    dest: Path,
    blobs: BlobStore,
    max_extracted_bytes: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract, validate and store *data*. Returns ``(manifest, media index)``.

    Documents land in *dest*; blob bytes go straight into the shared store, so
    the extracted tree holds only JSON regardless of how large the media was.

    *max_extracted_bytes* caps what the archive is allowed to expand to. The
    upload endpoint bounds the *compressed* body, which says nothing about the
    decompressed size — DEFLATE reaches roughly 1000:1 on repetitive input, so
    without this a bundle well under the upload cap fills the disk.
    """
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BundleError("not a readable zip archive") from exc

    # Emptied first, for the reason `capture` empties its own destination:
    # snapshot ids come from the database while these files live on disk, so a
    # directory that outlived its row — a restored dump, or an extraction that
    # failed on something other than a BundleError and skipped its cleanup —
    # would otherwise merge its pages into this upload and be restored as if
    # they had been uploaded.
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    stored: dict[str, bytes] = {}

    with archive:
        extracted = 0
        for info in archive.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            relative = _safe_relative(name)
            # Checked against the header before reading: `ZipExtFile` stops at
            # the declared size, so a member cannot quietly exceed it.
            extracted += info.file_size
            if max_extracted_bytes is not None and extracted > max_extracted_bytes:
                raise BundleError(
                    f"bundle expands to more than {max_extracted_bytes} bytes"
                )
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
    manifest = _require_manifest(_load(manifest_path, MANIFEST_NAME))

    index_path = dest / MEDIA_DIR / MEDIA_INDEX_NAME
    index = _load(index_path, MEDIA_INDEX_NAME) if index_path.is_file() else {}
    if not isinstance(index, dict):
        raise BundleError("media/index.json is not an object")

    # Digests are checked before they are used as names. They arrive as JSON
    # strings inside the bundle, not as archive members, so `_safe_relative`
    # never saw them — and `BlobStore` joins them onto the store root.
    for name, entry in sorted(index.items()):
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        if not is_digest(digest):
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

    _check_documents(dest, index)

    # Only commit blobs once every check has passed, so a rejected bundle
    # leaves no trace in the shared store. The digest is the one already
    # verified against the bytes above, so `put_known` does not hash again.
    for digest, payload in stored.items():
        blobs.put_known(digest, payload)

    if not (dest / REDIRECTS_NAME).is_file():
        (dest / REDIRECTS_NAME).write_text("[]\n")

    return manifest, index
