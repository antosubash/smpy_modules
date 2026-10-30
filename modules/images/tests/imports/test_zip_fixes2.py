"""Task 18 review fixes, round 2: the ZIP64 record where ``zipfile`` reads it,
untrusted values failing an item (never the run), a linear depth scan, and an
``external_source`` kept without an id."""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from sm_images import constants
from sm_images.imports import values, zip_import, zip_metadata, zip_safety
from sm_images.imports.zip_safety import Limits, ZipRejected, inspect

from tests.support.pipeline import jpeg
from tests.support.zip import import_zip, make_zip

pytestmark = pytest.mark.asyncio
FOUR = Limits(max_entries=4, max_entry_bytes=10**6, max_total_bytes=10**6, max_ratio=200)
BIG = Limits(max_entries=100, max_entry_bytes=10**8, max_total_bytes=10**9, max_ratio=200)


def _record(n: int, cd_size: int, cd_offset: int) -> bytes:
    return struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, n, n, cd_size, cd_offset)


def _forged(
    decoy_offset_field: bool = True, disk: int = 0, disks: int = 1, legacy_count: int = 1
) -> bytes:
    """Codex's repro: the locator's offset names a decoy record that agrees with
    the legacy one (1 entry); the record ``zipfile`` reads - the one right
    before the locator - says 5."""
    data = make_zip([(f"{i}.jpg", b"x") for i in range(5)])
    at = data.rfind(b"PK\x05\x06")
    _, _, _, _, _, cd_size, cd_offset, _ = struct.unpack("<4s4H2LH", data[at : at + 22])
    decoy_at, real_at = at, at + 56
    decoy = _record(1, cd_size, cd_offset)
    real = _record(5, cd_size, cd_offset)
    named = decoy_at if decoy_offset_field else real_at
    locator = struct.pack("<4sLQL", b"PK\x06\x07", disk, named, disks)
    legacy = struct.pack(
        "<4s4H2LH", b"PK\x05\x06", 0, 0, legacy_count, legacy_count, cd_size, cd_offset, 0
    )
    return data[:at] + decoy + real + locator + legacy


def _code(tmp_path: Path, data: bytes, limits: Limits) -> str:
    path = tmp_path / "z.zip"
    path.write_bytes(data)
    with (
        patch.object(zip_safety.zipfile, "ZipFile") as opened,
        pytest.raises(ZipRejected) as err,
    ):
        inspect(path, limits)
    opened.assert_not_called()
    return err.value.code


async def test_the_zip64_record_is_the_one_before_the_locator(tmp_path):
    assert _code(tmp_path, _forged(), FOUR) == "invalid_zip"
    # A locator naming any other place is refused even when the records agree.
    assert _code(tmp_path, _forged(legacy_count=0xFFFF), BIG) == "invalid_zip"


async def test_multi_disk_zip64_is_refused(tmp_path):
    assert _code(tmp_path, _forged(False, disk=1), BIG) == "invalid_zip"
    assert _code(tmp_path, _forged(False, disks=2), BIG) == "invalid_zip"


# --- untrusted values ------------------------------------------------------------


async def test_datetime_parsing_never_raises():
    for raw in (10**1000, -(10**1000), "9" * 1000, "1" * 100_000, float("inf"), 1e300):
        assert values.parse_datetime(raw) is None
    assert values.parse_datetime("2024-05-01T10:00:00Z") is not None


async def test_a_huge_captured_at_imports_without_a_date(imp):
    meta = b'{"a.jpg": {"captured_at": ' + b"9" * 1000 + b"}}"
    _, status = await import_zip(imp, make_zip([("metadata.json", meta), ("a.jpg", jpeg())]))
    assert status == "completed"
    (image,) = await imp.images()
    assert image.captured_at is None


async def test_an_entry_whose_values_break_fails_alone(imp, monkeypatch):
    real = zip_import.entry_item

    def fragile(entry, *args, **kwargs):
        if entry.filename == "bad.jpg":
            raise OverflowError("untrusted value")
        return real(entry, *args, **kwargs)

    monkeypatch.setattr(zip_import, "entry_item", fragile)
    members = [("a.jpg", jpeg((8, 6), "red")), ("bad.jpg", jpeg((8, 6), "blue"))]
    job, status = await import_zip(imp, make_zip(members))
    assert status == "completed"
    assert [(i.status.value, i.last_error) for i in await imp.items(job)] == [
        ("done", None),
        ("failed", "invalid_metadata"),
    ]


# --- a linear depth scan -----------------------------------------------------------


async def test_the_depth_scan_is_linear():
    hostile = ('"a\\' * 8000).encode()  # quadratic for a backtracking string regex
    started = time.perf_counter()
    with pytest.raises(ZipRejected):
        zip_metadata.parse_json(hostile)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    ("doc", "ok"),
    [
        ('{"a": "[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[["}', True),  # brackets in a string
        ('{"a": "\\"[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[["}', True),  # an escaped quote
        ('{"a": "\\\\", "b": ' + "[" * 40 + "]" * 40 + "}", False),  # an escaped backslash
        ('{"a": ' + "[" * 31 + "]" * 31 + "}", True),
        ('{"a": ' + "[" * 32 + "]" * 32 + "}", False),
    ],
)
async def test_the_depth_scan_reads_strings_and_escapes(doc, ok):
    if ok:
        assert isinstance(zip_metadata.parse_json(doc.encode()), dict)
    else:
        with pytest.raises(ZipRejected):
            zip_metadata.parse_json(doc.encode())


# --- external_source without an id -----------------------------------------------


async def test_an_external_source_is_kept_without_an_external_id(imp):
    meta = {"a.jpg": {"external_source": "lucas"}}
    data = make_zip([("metadata.json", json.dumps(meta).encode()), ("a.jpg", jpeg())])
    _, status = await import_zip(imp, data)
    assert status == "completed"
    (image,) = await imp.images()
    assert image.external_source == "lucas"
    assert image.external_id and image.external_source != constants.SOURCE_IMPORT
