"""Builders for Mailchimp export bytes: CSV text and (optionally doctored) ZIP archives."""

from __future__ import annotations

import csv
import io
import struct
import zipfile
from collections.abc import Mapping, Sequence

_CENTRAL = b"PK\x01\x02"
_LOCAL = b"PK\x03\x04"


def csv_bytes(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    delimiter: str = ",",
    bom: bool = False,
) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    data = out.getvalue().encode()
    return (b"\xef\xbb\xbf" + data) if bom else data


def zip_bytes(
    members: Mapping[str, bytes],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    flag_bits: int | None = None,
    declared_size: int | None = None,
) -> bytes:
    """A ZIP of ``members``; ``flag_bits`` and ``declared_size`` rewrite every central header."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    raw = bytearray(buf.getvalue())
    pos = raw.find(_CENTRAL)
    while pos != -1:
        if flag_bits is not None:
            struct.pack_into("<H", raw, pos + 8, flag_bits)
        if declared_size is not None:
            struct.pack_into("<I", raw, pos + 24, declared_size)
        pos = raw.find(_CENTRAL, pos + 4)
    return bytes(raw)
