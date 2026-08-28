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
    page = json.dumps({"draft_data": {"src": "asset://ghost.jpg"}}).encode()
    data = _zip({**_minimal(), "pages/home.json": page})
    with pytest.raises(BundleError, match="references media it does not contain"):
        read_zip(data, tmp_path / "out", BlobStore(tmp_path / "blobs"))


def test_a_rejected_bundle_leaves_no_blob_behind(tmp_path):
    blobs = BlobStore(tmp_path / "blobs")
    page = json.dumps({"draft_data": {"src": "asset://ghost.jpg"}}).encode()
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
    (bundle / "pages" / "home.json").write_text(
        json.dumps({"draft_data": {"src": "asset://hero.jpg"}})
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
