"""A ZIP's end records, read before ``ZipFile`` is ever built: :func:`directory_bounds`.

``zipfile.ZipFile`` parses the whole central directory into memory on open,
and it believes a ZIP64 end record whenever a ZIP64 locator sits right before
the legacy one - whatever the legacy record says. So the bounds are read the
same way: the locator is **always** looked for; when present its record's
count and directory size are the ones that count, and a legacy record that
names other (non-sentinel) values is a forgery (``invalid_zip``). Only then
are the bounds capped, by the caller.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO, Final

__all__ = ["ZipRejected", "directory_bounds"]

_EOCD: Final = (b"PK\x05\x06", 22)
_ZIP64_LOCATOR: Final = (b"PK\x06\x07", 20)
_ZIP64_EOCD: Final = (b"PK\x06\x06", 56)
_COUNT_SENTINEL: Final = 0xFFFF
_SIZE_SENTINEL: Final = 0xFFFFFFFF
_MAX_COMMENT: Final = 0xFFFF


class ZipRejected(Exception):  # noqa: N818 - a verdict, carried by its code
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _read_at(handle: BinaryIO, offset: int, size: int) -> bytes:
    handle.seek(offset)
    return handle.read(size)


def _zip64(handle: BinaryIO, eocd_at: int) -> tuple[int, int] | None:
    """The ZIP64 record's ``(count, directory size)``, or ``None`` without a locator."""
    locator_at = eocd_at - _ZIP64_LOCATOR[1]
    if locator_at < 0:
        return None
    locator = _read_at(handle, locator_at, _ZIP64_LOCATOR[1])
    if not locator.startswith(_ZIP64_LOCATOR[0]):
        return None
    record = _read_at(handle, struct.unpack("<4sLQL", locator)[2], _ZIP64_EOCD[1])
    if len(record) < _ZIP64_EOCD[1] or not record.startswith(_ZIP64_EOCD[0]):
        raise ZipRejected("invalid_zip")
    entries, cd_size = struct.unpack("<QQ", record[32:48])
    return int(entries), int(cd_size)


def directory_bounds(path: Path) -> tuple[int, int]:
    """``(entry count, central directory bytes)`` as ``zipfile`` will see them."""
    file_size = path.stat().st_size
    tail_size = min(file_size, _EOCD[1] + _MAX_COMMENT)
    with path.open("rb") as handle:
        tail = _read_at(handle, file_size - tail_size, tail_size)
        at = tail.rfind(_EOCD[0])
        if at < 0 or len(tail) - at < _EOCD[1]:
            raise ZipRejected("invalid_zip")
        fields = struct.unpack("<4s4H2LH", tail[at : at + _EOCD[1]])
        entries, cd_size = int(fields[4]), int(fields[5])
        wide = _zip64(handle, file_size - tail_size + at)
    if wide is None:
        if entries == _COUNT_SENTINEL or cd_size == _SIZE_SENTINEL:
            raise ZipRejected("invalid_zip")  # a sentinel with no ZIP64 record behind it
        return entries, cd_size
    if (entries != _COUNT_SENTINEL and entries != wide[0]) or (
        cd_size != _SIZE_SENTINEL and cd_size != wide[1]
    ):
        raise ZipRejected("invalid_zip")  # the two records disagree
    return wide
