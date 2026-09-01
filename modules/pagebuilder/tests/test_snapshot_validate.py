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


def test_accepts_one_slug_in_two_languages(tmp_path):
    """Two languages publishing ``about`` is the ordinary case, not a clash.

    The duplicate guard keys on ``(locale, slug)`` because that is what the
    database is unique on. Keyed on the bare slug it would refuse a bundle
    every bilingual site produces.
    """
    files = _minimal() | {
        "pages/en.json": _page("about", locale="en"),
        "pages/de.json": _page("about", locale="de"),
    }
    read_zip(_zip(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))
    assert (tmp_path / "out" / "pages" / "de.json").is_file()


def test_still_rejects_one_slug_twice_in_one_language(tmp_path):
    files = _minimal() | {
        "pages/a.json": _page("about", locale="de", draft_data={"root": "a"}),
        "pages/b.json": _page("about", locale="de", draft_data={"root": "b"}),
    }
    with pytest.raises(BundleError, match="repeats slug 'about' in de"):
        read_zip(_zip(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_a_document_with_no_locale_collides_with_the_default_one(tmp_path):
    """A v1 document reads as the default locale, so it is the *same* page as
    an explicit ``en`` one — not a second page that quietly overwrites it."""
    files = _minimal() | {
        "pages/a.json": _page("about"),
        "pages/b.json": _page("about", locale="en"),
    }
    with pytest.raises(BundleError, match="repeats slug 'about' in en"):
        read_zip(_zip(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_rejects_a_locale_that_is_not_a_language_tag(tmp_path):
    """Junk would otherwise reach the column as a page's language."""
    files = _minimal() | {"pages/a.json": _page("about", locale="../etc")}
    with pytest.raises(BundleError, match="unreadable locale"):
        read_zip(_zip(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_accepts_a_redirect_slug_repeated_across_languages(tmp_path):
    """``(locale, from_slug)`` is unique, so one retired address per language
    is two rows, not a duplicate."""
    rows = json.dumps(
        [
            {"from_slug": "info", "locale": "en", "to_slug": "about"},
            {"from_slug": "info", "locale": "de", "to_slug": "about"},
        ]
    ).encode()
    files = _minimal() | {
        "pages/a.json": _page("about", locale="en"),
        "pages/b.json": _page("about", locale="de"),
        "redirects.json": rows,
    }
    read_zip(_zip(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_still_rejects_a_redirect_slug_repeated_within_one_language(tmp_path):
    rows = json.dumps(
        [
            {"from_slug": "info", "locale": "de", "to_slug": "about"},
            {"from_slug": "info", "locale": "de", "to_slug": "about"},
        ]
    ).encode()
    files = _minimal() | {
        "pages/b.json": _page("about", locale="de"),
        "redirects.json": rows,
    }
    with pytest.raises(BundleError, match="repeats from_slug 'info'"):
        read_zip(_zip(files), tmp_path / "out", BlobStore(tmp_path / "blobs"))
