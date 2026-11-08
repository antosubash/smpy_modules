from __future__ import annotations

import io
import zipfile

import pytest
from sm_newsletter.core.errors_import import (
    ImportNotCsv,
    ImportTooLarge,
    ImportTooManyFiles,
    ImportZipUnsafe,
)
from sm_newsletter.imports.archive import sources
from sm_newsletter.imports.constants import MAX_FILES, MAX_ZIP_ENTRIES

from tests.imports.fixtures import csv_bytes, zip_bytes

CSV = csv_bytes(["Email Address"], [["a@example.com"]])


def _upload(name: str, data: bytes) -> tuple[str, io.BytesIO]:
    return name, io.BytesIO(data)


def test_zip_members_selected():
    data = zip_bytes(
        {
            "__MACOSX/x.csv": CSV,
            ".hidden.csv": CSV,
            "readme.txt": b"hi",
            "nested/dir/subscribed_x.csv": CSV,
        }
    )
    found = sources([_upload("export.zip", data)])
    assert [(s.index, s.name) for s in found] == [(0, "subscribed_x.csv")]
    assert found[0].open().read() == CSV
    assert found[0].open().read() == CSV  # re-openable


def test_plain_csv_parts():
    parts = [_upload(f"p{i}.csv", CSV) for i in range(3)]
    found = sources(parts)
    assert [(s.index, s.name) for s in found] == [(0, "p0.csv"), (1, "p1.csv"), (2, "p2.csv")]
    assert found[1].open().read() == CSV
    assert found[1].open().read() == CSV


def test_the_file_and_entry_caps_are_inclusive():
    four = [_upload(f"p{i}.csv", CSV) for i in range(MAX_FILES)]
    assert len(sources(four)) == MAX_FILES
    full = zip_bytes({f"{i}.csv": CSV for i in range(MAX_ZIP_ENTRIES)})
    assert len(sources([_upload("x.zip", full)])) == MAX_ZIP_ENTRIES


def test_name_is_basename_without_control_chars():
    (found,) = sources([_upload("C:\\tmp\\a\x01b.csv", CSV)])
    assert found.name == "ab.csv"
    (long,) = sources([_upload("x" * 300 + ".csv", CSV)])
    assert len(long.name) <= 200


MIB = 1024 * 1024


@pytest.mark.parametrize(
    ("uploads", "error"),
    [
        ([("a.zip", zip_bytes({"a.csv": CSV})), ("b.csv", CSV)], ImportTooManyFiles),
        ([(f"{i}.csv", CSV) for i in range(5)], ImportTooManyFiles),
        ([("a.xlsx", b"PK")], ImportNotCsv),
        ([("a.zip", zip_bytes({"a.csv": CSV}, flag_bits=0x1))], ImportZipUnsafe),
        ([("a.zip", zip_bytes({"a.csv": CSV}, declared_size=300 * MIB))], ImportTooLarge),
        ([("a.zip", zip_bytes({"a.csv": b"x" * 5000}, declared_size=5000 * 500))], ImportZipUnsafe),
        ([("a.zip", zip_bytes({"a.csv": CSV}, compression=zipfile.ZIP_BZIP2))], ImportZipUnsafe),
        ([("a.zip", zip_bytes({f"{i}.csv": CSV for i in range(17)}))], ImportZipUnsafe),
        ([("a.zip", b"PK\x03\x04 not really a zip")], ImportZipUnsafe),
    ],
)
def test_archive_refusals(uploads, error):
    with pytest.raises(error) as caught:
        sources([_upload(name, data) for name, data in uploads])
    assert "a.csv" not in caught.value.detail
