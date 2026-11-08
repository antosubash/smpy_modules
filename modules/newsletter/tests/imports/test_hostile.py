"""Lying ZIP content and oversize lines refuse the file; none echoes a value."""

from __future__ import annotations

import io
import zipfile

import pytest
from sm_newsletter.core.errors_import import ImportMalformedCsv, ImportZipUnsafe
from sm_newsletter.imports import mailchimp as mc
from sm_newsletter.imports.archive import sources
from sm_newsletter.imports.constants import MAX_HEADER_KEY, MAX_LINE

from tests.imports.fixtures import csv_bytes, zip_bytes

ROWS = [[f"user{i}@example.com", "Ada"] for i in range(400)]
BODY = csv_bytes(["Email Address", "First Name"], ROWS)


def _drain(data: bytes, name: str = "a.csv") -> None:
    (source,) = sources([("x.zip", io.BytesIO(data))])
    stream = mc.text_stream(source.open())
    header = mc.read_header(stream)
    list(mc.read_rows(stream, header, "subscribed"))


def _stored(body: bytes = BODY) -> bytearray:
    return bytearray(zip_bytes({"a.csv": body}, compression=zipfile.ZIP_STORED))


def test_wrong_crc_is_a_refusal():
    raw = _stored()
    at = raw.find(b"user5@example.com")
    raw[at : at + 5] = b"XXXXX"
    with pytest.raises(ImportZipUnsafe):
        _drain(bytes(raw))


def test_shrunk_declared_size_is_a_refusal():
    with pytest.raises(ImportZipUnsafe):
        _drain(zip_bytes({"a.csv": BODY}, declared_size=len(BODY) // 2))


def test_corrupt_deflate_stream_is_a_refusal():
    raw = bytearray(zip_bytes({"a.csv": BODY}))
    start = 30 + len("a.csv")
    raw[start + 8 : start + 40] = b"\xff" * 32
    with pytest.raises(ImportZipUnsafe):
        _drain(bytes(raw))


def test_truncated_deflate_stream_is_a_refusal():
    raw = zip_bytes({"a.csv": BODY})
    cut = raw.find(b"PK\x01\x02")
    corrupt = raw[: cut - 20] + raw[cut:]
    with pytest.raises(ImportZipUnsafe):
        _drain(corrupt)


def test_local_name_mismatch_refuses_on_open():
    raw = bytearray(zip_bytes({"a.csv": BODY}))
    raw[raw.find(b"a.csv") : raw.find(b"a.csv") + 5] = b"b.csv"
    (source,) = sources([("x.zip", io.BytesIO(bytes(raw)))])
    with pytest.raises(ImportZipUnsafe):
        source.open()


def test_unterminated_oversize_line_is_refused_with_its_line():
    data = b"Email Address\na@example.com\n" + b"x" * (MAX_LINE + 10)
    stream = mc.text_stream(io.BytesIO(data))
    header = mc.read_header(stream)
    with pytest.raises(ImportMalformedCsv) as caught:
        list(mc.read_rows(stream, header, "subscribed"))
    assert "line 3" in caught.value.detail


def test_oversize_header_line_is_refused():
    stream = mc.text_stream(io.BytesIO(b"E" * (MAX_LINE + 1)))
    with pytest.raises(ImportMalformedCsv) as caught:
        mc.read_header(stream)
    assert "line 1" in caught.value.detail


def test_header_keys_in_errors_are_capped():
    name = "F" * 5000
    data = csv_bytes(["Email Address", name], [["a@example.com", "x" * 5000]])
    stream = mc.text_stream(io.BytesIO(data))
    header = mc.read_header(stream)
    errors = [r for r in mc.read_rows(stream, header, "subscribed") if isinstance(r, mc.RowError)]
    assert errors
    assert all(len(e.field or "") <= MAX_HEADER_KEY for e in errors)
    assert all(len(n) <= MAX_HEADER_KEY for n in header.names)


def test_every_email_header_is_excluded_from_mappable():
    data = csv_bytes(["Email Address", "E-Mail", "First Name"], [])
    header = mc.read_header(mc.text_stream(io.BytesIO(data)))
    assert [header.names[i] for i in header.mappable] == ["First Name"]


def _line_of(length: int) -> bytes:
    """A row line of exactly ``length`` bytes with its newline, from short cells."""
    cells = (length - len(b"a@example.com\n")) // 2
    line = b"a@example.com" + b",x" * cells + b"\n"
    return line + b"" if len(line) == length else line[:-1] + b"x\n"


def _parse(row: bytes) -> list:
    stream = mc.text_stream(io.BytesIO(b"Email Address\n" + row))
    header = mc.read_header(stream)
    return list(mc.read_rows(stream, header, "subscribed"))


def test_a_line_of_exactly_max_line_bytes_is_accepted():
    row = _line_of(MAX_LINE)
    assert len(row) == MAX_LINE
    assert [type(r) for r in _parse(row)] == [mc.Parsed]


def test_a_line_one_byte_over_max_line_is_refused():
    row = _line_of(MAX_LINE + 1)
    assert len(row) == MAX_LINE + 1
    with pytest.raises(ImportMalformedCsv) as caught:
        _parse(row)
    assert "line 2" in caught.value.detail
