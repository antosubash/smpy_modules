"""Document-level bundle checks, exercised through `read_zip`.

Separate from ``test_snapshot_archive.py`` — which is at the repo's 300-line
cap — and matching the source split: ``archive.py`` keeps to zip mechanics
while ``validate.py`` owns "is this a document apply could survive?".
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest
from pagebuilder.snapshots.archive import BundleError, read_zip
from pagebuilder.snapshots.blobs import BlobStore

_IMAGE = b"image-bytes"
_SHA = hashlib.sha256(_IMAGE).hexdigest()


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _minimal() -> dict[str, bytes]:
    manifest = json.dumps({"format_version": 1}).encode()
    return {"manifest.json": manifest, "media/index.json": b"{}"}


def _page(slug: str = "home", **extra) -> bytes:
    return json.dumps({"slug": slug, "status": "draft", **extra}).encode()


def test_rejects_two_page_files_claiming_one_slug(tmp_path):
    """`read_documents` keys pages by slug, so the loser vanishes silently.

    Nothing downstream could report it either: the plan is built from that
    deduplicated dict, so an approver would see one page and no warning that
    a second document had been dropped. Refused for the same reason a
    repeated `from_slug` is.
    """
    files = _minimal() | {
        "pages/a.json": _page("home", draft_data={"root": "a"}),
        "pages/b.json": _page("home", draft_data={"root": "b"}),
    }
    with pytest.raises(BundleError, match="repeats slug 'home'"):
        read_zip(_zip(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_accepts_distinct_slugs_across_files(tmp_path):
    """The guard keys on the slug, not on how many page files there are."""
    files = _minimal() | {
        "pages/a.json": _page("home"),
        "pages/b.json": _page("about"),
    }
    read_zip(_zip(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))
    assert (tmp_path / "out" / "pages" / "a.json").is_file()
    assert (tmp_path / "out" / "pages" / "b.json").is_file()
