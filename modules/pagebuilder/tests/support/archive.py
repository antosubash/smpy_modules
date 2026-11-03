"""Snapshot archive payload builders."""

import hashlib
import io
import json
import zipfile

_IMAGE = b"image-bytes"
_SHA = hashlib.sha256(_IMAGE).hexdigest()


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _manifest(**extra) -> bytes:
    return json.dumps({"format_version": 1, **extra}).encode()


def _minimal() -> dict[str, bytes]:
    return {"manifest.json": _manifest(), "media/index.json": b"{}"}


def _page(slug: str = "home", **extra) -> bytes:
    """A page document with the keys `read_zip` insists every page carries."""
    return json.dumps({"slug": slug, "status": "draft", **extra}).encode()
