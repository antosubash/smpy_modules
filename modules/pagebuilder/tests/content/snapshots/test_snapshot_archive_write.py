from __future__ import annotations

import json

import pytest
from pagebuilder.content.snapshots.archive import BundleError, read_zip, write_zip
from pagebuilder.content.snapshots.blobs import BlobStore

from tests.support.archive import _IMAGE, _SHA, _manifest, _page


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
