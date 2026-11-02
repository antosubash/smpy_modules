"""``imports.zip_safety``: refusals decided before a byte is imported, and caps
enforced on the bytes actually decompressed - never on what a header claims."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from sm_images.ingest.imports import zip_safety
from sm_images.ingest.imports.zip_safety import (
    Limits,
    ZipRejected,
    inspect,
    is_unsafe_name,
    read_entry,
)

from tests.support.zip import encrypted, lie_sizes, make_zip, overlapping, with_symlink

BIG = Limits(max_entries=100, max_entry_bytes=10**8, max_total_bytes=10**9, max_ratio=200)


def _file(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "a.zip"
    path.write_bytes(data)
    return path


def _code(tmp_path: Path, data: bytes, limits: Limits = BIG) -> str:
    with pytest.raises(ZipRejected) as err:
        inspect(_file(tmp_path, data), limits)
    return err.value.code


@pytest.mark.parametrize(
    "name",
    ["../evil.jpg", "a/../../evil.jpg", "/etc/x.jpg", "C:\\x.jpg", "..\\x.jpg", "a\x00.jpg"],
)
def test_unsafe_names(name):
    assert is_unsafe_name(name)


@pytest.mark.parametrize("name", ["a.jpg", "dir/b.png", "x..y.jpg", "dir/./c.jpg"])
def test_safe_names(name):
    assert not is_unsafe_name(name)


def test_zip_slip_and_absolute_paths_refuse_the_archive(tmp_path):
    for bad in ("../../escape.jpg", "/abs.jpg", "C:/x.jpg"):
        assert _code(tmp_path, make_zip([("ok.jpg", b"1"), (bad, b"2")])) == "unsafe_path"


def test_symlink_encrypted_compression_and_overlap_are_refused(tmp_path):
    assert _code(tmp_path, with_symlink("link.jpg")) == "symlink_entry"
    assert _code(tmp_path, encrypted(make_zip([("a.jpg", b"abc")]))) == "encrypted_entry"
    bz = make_zip([("a.jpg", b"abc")], zipfile.ZIP_BZIP2)
    assert _code(tmp_path, bz) == "unsupported_compression"
    assert _code(tmp_path, overlapping()) == "overlapping_entries"


def test_nested_archives_are_refused_by_name_and_by_content(tmp_path):
    inner = make_zip([("x.jpg", b"1")])
    assert _code(tmp_path, make_zip([("more.zip", inner)])) == "nested_archive"
    assert _code(tmp_path, make_zip([("sneaky.jpg", inner)])) == "nested_archive"
    assert _code(tmp_path, make_zip([("t.tar.gz", b"\x1f\x8b\x08rest")])) == "nested_archive"


def test_entry_count_is_capped_before_zipfile_parses_the_directory(tmp_path):
    path = _file(tmp_path, make_zip([(f"{i}.jpg", b"x") for i in range(5)]))
    four = Limits(max_entries=4, max_entry_bytes=10**6, max_total_bytes=10**6, max_ratio=200)
    with patch.object(zip_safety.zipfile, "ZipFile") as opened, pytest.raises(ZipRejected) as err:
        inspect(path, four)
    assert err.value.code == "too_many_entries"
    opened.assert_not_called()


def test_not_a_zip(tmp_path):
    assert _code(tmp_path, b"not a zip at all") == "invalid_zip"


def test_lying_header_is_stopped_by_the_actual_entry_bytes(tmp_path):
    data = lie_sizes(make_zip([("a.jpg", os.urandom(5000))]), 10)
    small = Limits(max_entries=10, max_entry_bytes=1000, max_total_bytes=10**6, max_ratio=200)
    assert _code(tmp_path, data, small) == "entry_too_large"


def test_lying_header_is_stopped_by_the_actual_total(tmp_path):
    members = [(f"{i}.jpg", os.urandom(3000)) for i in range(4)]
    data = lie_sizes(make_zip(members), 10)  # the headers claim 40 bytes in all
    capped = Limits(max_entries=10, max_entry_bytes=10**6, max_total_bytes=10_000, max_ratio=200)
    assert _code(tmp_path, data, capped) == "uncompressed_too_large"


def test_compression_ratio_is_measured_on_real_bytes(tmp_path):
    bomb = make_zip([("bomb.jpg", b"\x00" * (3 * 1024 * 1024))])
    assert _code(tmp_path, bomb) == "suspicious_ratio"
    assert _code(tmp_path, lie_sizes(bomb, 1)) == "suspicious_ratio"


def test_entries_keep_archive_order_duplicates_and_skip_folders_and_junk(tmp_path):
    data = make_zip(
        [
            ("b.jpg", b"1"),
            ("dir/", b""),
            ("dir/a.jpg", b"2"),
            ("b.jpg", b"3"),
            ("__MACOSX/dir/._a.jpg", b"4"),
            (".DS_Store", b"5"),
            ("metadata.json", b"{}"),
        ]
    )
    plan = inspect(_file(tmp_path, data), BIG)
    assert [(e.index, e.name, e.filename) for e in plan.entries] == [
        (0, "b.jpg", "b.jpg"),
        (1, "dir/a.jpg", "a.jpg"),
        (2, "b.jpg", "b.jpg"),
    ]
    with zipfile.ZipFile(_file(tmp_path, data)) as zf:
        infos = zf.infolist()
        assert [read_entry(zf, infos[e.position], 10) for e in plan.entries] == [b"1", b"2", b"3"]
        assert read_entry(zf, infos[0], 0) is None  # over the per-image cap


def test_metadata_json_is_bounded_and_parsed(tmp_path):
    doc = {"a.jpg": {"latitude": 1.5}}
    plan = inspect(_file(tmp_path, make_zip([("metadata.json", json.dumps(doc).encode())])), BIG)
    assert plan.metadata == doc
    with patch.object(zip_safety, "METADATA_MAX_BYTES", 5):
        assert _code(tmp_path, make_zip([("metadata.json", b"{" + b" " * 10 + b"}")])) == (
            "metadata_too_large"
        )
    for bad in (b"[1, 2]", b"{nope", b"\xff\xfe"):
        assert _code(tmp_path, make_zip([("metadata.json", bad)])) == "metadata_invalid"
    nested = make_zip([("dir/metadata.json", b"{}")])
    assert inspect(_file(tmp_path, nested), BIG).metadata == {}
