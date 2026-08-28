from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest
from pagebuilder.snapshots.archive import BundleError, read_zip, write_zip
from pagebuilder.snapshots.blobs import BlobStore

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


def test_reads_a_minimal_bundle(tmp_path):
    manifest, index = read_zip(
        _zip(_minimal()), tmp_path / "out", BlobStore(tmp_path / "blobs")
    )
    assert manifest["format_version"] == 1
    assert index == {}
    # A bundle without redirects still yields a readable redirects document.
    assert (tmp_path / "out" / "redirects.json").read_text().strip() == "[]"


def test_unknown_format_version_is_refused(tmp_path):
    data = _zip({"manifest.json": json.dumps({"format_version": 99}).encode()})
    with pytest.raises(BundleError, match="format version"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_missing_manifest_is_refused(tmp_path):
    with pytest.raises(BundleError, match="manifest"):
        read_zip(
            _zip({"pages/a.json": b"{}"}), tmp_path / "out", BlobStore(tmp_path / "b")
        )


def test_not_a_zip_is_refused(tmp_path):
    with pytest.raises(BundleError, match="readable zip"):
        read_zip(b"definitely not a zip", tmp_path / "out", BlobStore(tmp_path / "b"))


def test_path_traversal_entry_is_refused(tmp_path):
    data = _zip({**_minimal(), "../escape.json": b"{}"})
    with pytest.raises(BundleError, match="unsafe path"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))
    assert not (tmp_path / "escape.json").exists()


def test_absolute_path_entry_is_refused(tmp_path):
    data = _zip({**_minimal(), "/etc/passwd": b"x"})
    with pytest.raises(BundleError, match="unsafe path"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_blob_that_does_not_match_its_name_is_refused(tmp_path):
    data = _zip({**_minimal(), f"media/blobs/{_SHA}": b"tampered"})
    with pytest.raises(BundleError, match="does not match"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_index_entry_without_its_bytes_is_refused(tmp_path):
    index = {"hero.jpg": {"sha256": _SHA, "original_filename": "hero.jpg"}}
    data = _zip({"manifest.json": _manifest(), "media/index.json": json.dumps(index).encode()})
    with pytest.raises(BundleError, match="missing the bytes"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_sentinel_missing_from_the_index_is_refused(tmp_path):
    page = _page(draft_data={"src": "asset://ghost.jpg"})
    data = _zip({**_minimal(), "pages/home.json": page})
    with pytest.raises(BundleError, match="references media it does not contain"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_a_rejected_bundle_leaves_no_blob_behind(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    page = _page(draft_data={"src": "asset://ghost.jpg"})
    index = {"hero.jpg": {"sha256": _SHA, "original_filename": "hero.jpg"}}
    data = _zip(
        {
            "manifest.json": _manifest(),
            "media/index.json": json.dumps(index).encode(),
            f"media/blobs/{_SHA}": _IMAGE,
            "pages/home.json": page,
        }
    )
    with pytest.raises(BundleError):
        read_zip(data, tmp_path / "out", blobs)
    assert not blobs.exists(_SHA)


def test_index_digest_that_traverses_is_refused(tmp_path):
    """The attack the zip-member guard does not cover.

    `media/index.json` carries digest *strings*, not archive member names, so
    `_safe_relative` never inspects them. Left unchecked, apply would call
    `BlobStore.get("../secret.txt")` and read whatever the server can.
    """
    (tmp_path / "secret.txt").write_bytes(b"private")
    index = {"hero.jpg": {"sha256": "../secret.txt", "original_filename": "hero.jpg"}}
    data = _zip(
        {"manifest.json": _manifest(), "media/index.json": json.dumps(index).encode()}
    )
    with pytest.raises(BundleError, match="no valid sha256"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_index_digest_that_is_absolute_is_refused(tmp_path):
    index = {"hero.jpg": {"sha256": "/etc/hosts", "original_filename": "hero.jpg"}}
    data = _zip(
        {"manifest.json": _manifest(), "media/index.json": json.dumps(index).encode()}
    )
    with pytest.raises(BundleError, match="no valid sha256"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_index_entry_that_is_not_an_object_is_refused(tmp_path):
    data = _zip(
        {
            "manifest.json": _manifest(),
            "media/index.json": json.dumps({"hero.jpg": "nope"}).encode(),
        }
    )
    with pytest.raises(BundleError, match="no valid sha256"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_round_trip_through_write_zip(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    sha = blobs.put(_IMAGE)
    bundle = tmp_path / "bundle"
    (bundle / "media").mkdir(parents=True)
    (bundle / "manifest.json").write_bytes(_manifest())
    (bundle / "media" / "index.json").write_text(
        json.dumps({"hero.jpg": {"sha256": sha, "original_filename": "hero.jpg"}})
    )
    (bundle / "pages").mkdir()
    (bundle / "pages" / "home.json").write_bytes(
        _page(draft_data={"src": "asset://hero.jpg"})
    )

    target = tmp_path / "out.zip"
    size = write_zip(bundle, blobs, [{"sha256": sha}], target)
    assert size > 0

    manifest, index = read_zip(
        target.read_bytes(), tmp_path / "back", BlobStore(tmp_path / "blobs2")
    )
    assert manifest["format_version"] == 1
    assert index["hero.jpg"]["sha256"] == sha
    assert BlobStore(tmp_path / "blobs2").get(sha) == _IMAGE


def test_a_page_with_an_unknown_status_is_refused(tmp_path):
    """Rejected at the boundary, not halfway through a restore.

    `apply_payload` coerces this straight into `PageStatus`, so without a
    check here a hand-edited bundle uploads and stages cleanly and then 500s
    inside apply — after the pre-restore snapshot has already been taken.
    """
    page = json.dumps({"slug": "home", "status": "archived"}).encode()
    data = _zip({**_minimal(), "pages/home.json": page})
    with pytest.raises(BundleError, match="unknown status"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_a_page_without_a_slug_is_refused(tmp_path):
    data = _zip({**_minimal(), "pages/home.json": b'{"status": "draft"}'})
    with pytest.raises(BundleError, match="has no slug"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_a_page_with_an_unreadable_schedule_is_refused(tmp_path):
    data = _zip({**_minimal(), "pages/home.json": _page(publish_at="whenever")})
    with pytest.raises(BundleError, match="unreadable publish_at"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_a_document_that_is_not_json_is_refused(tmp_path):
    """A JSONDecodeError is a ValueError, not a BundleError.

    Left to escape, it bypassed the caller's cleanup and left an extracted
    directory on disk under a snapshot id the database had rolled back.
    """
    data = _zip({**_minimal(), "pages/home.json": b"{not json"})
    with pytest.raises(BundleError, match="is not valid JSON"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_a_bundle_that_expands_past_the_cap_is_refused(tmp_path):
    """The compressed body says nothing about what it expands to."""
    data = _zip({**_minimal(), "pages/home.json": _page(title="x" * 100_000)})
    with pytest.raises(BundleError, match="expands to more than"):
        read_zip(
            data,
            tmp_path / "out",
            BlobStore(tmp_path / "blobs"),
            max_extracted_bytes=50_000,
        )


def test_extraction_does_not_inherit_a_leftover_directory(tmp_path):
    """Snapshot ids come from the database; these files live on disk.

    A directory that outlived its row must not merge its pages into the next
    upload that lands on the same id.
    """
    dest = tmp_path / "out"
    (dest / "pages").mkdir(parents=True)
    (dest / "pages" / "ghost.json").write_bytes(_page(slug="ghost"))

    read_zip(
        _zip({**_minimal(), "pages/home.json": _page()}),
        dest,
        BlobStore(tmp_path / "blobs"),
    )
    assert not (dest / "pages" / "ghost.json").exists()
    assert (dest / "pages" / "home.json").exists()


def test_writing_a_snapshot_whose_bytes_are_gone_fails_loudly(tmp_path):
    """Better than a zip every importing host rejects for unclear reasons."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_bytes(_manifest())
    with pytest.raises(BundleError, match="missing the bytes"):
        write_zip(
            bundle,
            BlobStore(tmp_path / "blobs"),
            [{"sha256": _SHA}],
            tmp_path / "o.zip",
        )
