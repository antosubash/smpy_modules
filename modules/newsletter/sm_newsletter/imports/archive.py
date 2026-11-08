"""Which CSV files an upload holds, after the size and ZIP safety checks (R7).

Pure: no database. Errors name the part by index, never by file name.
"""

from __future__ import annotations

import os
import zipfile
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import BinaryIO

from sm_newsletter.core.errors_import import (
    ImportNotCsv,
    ImportTooLarge,
    ImportTooManyFiles,
    ImportZipUnsafe,
)
from sm_newsletter.imports.constants import (
    MAX_ENTRY_BYTES,
    MAX_FILES,
    MAX_RATIO,
    MAX_TOTAL_BYTES,
    MAX_ZIP_ENTRIES,
)

MAX_NAME = 200
ARCHIVE_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError)
"""What a lying or corrupt entry raises while it is read."""
_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


@dataclass(frozen=True)
class Source:
    """One CSV file; ``open`` returns a fresh stream at offset 0 each call."""

    index: int
    name: str
    open: Callable[[], BinaryIO]
    owned: bool = False
    """``open`` returns a stream of its own (a ZIP entry) that the reader closes; a CSV upload's
    stream is the caller's and is reused."""


def clean_name(raw: str) -> str:
    base = raw.replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(c for c in base if c.isprintable())[:MAX_NAME]


def _is_zip(name: str) -> bool:
    return name.casefold().endswith(".zip")


def _is_csv(name: str) -> bool:
    return name.casefold().endswith(".csv")


def sources(uploads: Sequence[tuple[str, BinaryIO]]) -> list[Source]:
    """One ZIP alone (holding 1..``MAX_FILES`` CSVs), or 1..``MAX_FILES`` CSV parts."""
    if not uploads:
        raise ImportNotCsv
    if len(uploads) > MAX_FILES or (len(uploads) > 1 and any(_is_zip(n) for n, _ in uploads)):
        raise ImportTooManyFiles
    if len(uploads) == 1 and _is_zip(uploads[0][0]):
        return _zip_sources(uploads[0][1])
    if not all(_is_csv(name) for name, _ in uploads):
        raise ImportNotCsv
    found = [_csv_source(i, name, stream) for i, (name, stream) in enumerate(uploads)]
    sizes = [_size(stream) for _, stream in uploads]
    _check_sizes(sizes)
    return found


def _size(stream: BinaryIO) -> int:
    return stream.seek(0, os.SEEK_END)


def _check_sizes(sizes: Sequence[int]) -> None:
    if any(s > MAX_ENTRY_BYTES for s in sizes) or sum(sizes) > MAX_TOTAL_BYTES:
        raise ImportTooLarge


def _csv_source(index: int, name: str, stream: BinaryIO) -> Source:
    def open_stream() -> BinaryIO:
        stream.seek(0)
        return stream

    return Source(index, clean_name(name), open_stream)


def _zip_sources(stream: BinaryIO) -> list[Source]:
    try:
        archive = zipfile.ZipFile(stream)
        infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError) as exc:
        raise ImportZipUnsafe from exc
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ImportZipUnsafe
    files = [i for i in infos if not i.is_dir()]
    for info in files:
        _check_entry(info)
    _check_sizes([i.file_size for i in files])
    chosen = [i for i in files if _wanted(i.filename)]
    if not chosen:
        raise ImportNotCsv
    if len(chosen) > MAX_FILES:  # the same cap as loose parts; other entries count toward 16 only
        raise ImportTooManyFiles
    return [
        Source(n, clean_name(info.filename), _opener(archive, info), owned=True)
        for n, info in enumerate(chosen)
    ]


def _check_entry(info: zipfile.ZipInfo) -> None:
    if info.flag_bits & 0x1 or info.compress_type not in _METHODS:
        raise ImportZipUnsafe
    if info.file_size > MAX_ENTRY_BYTES:
        return  # reported as too large by the caller's size check
    if info.file_size and (
        info.compress_size == 0 or info.file_size / info.compress_size > MAX_RATIO
    ):
        raise ImportZipUnsafe


def _wanted(filename: str) -> bool:
    parts = [p for p in filename.replace("\\", "/").split("/") if p]
    if not parts or parts[0] == "__MACOSX" or parts[-1].startswith("."):
        return False
    return _is_csv(parts[-1])


def _opener(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> Callable[[], BinaryIO]:
    def open_entry() -> BinaryIO:
        try:
            return archive.open(info)  # type: ignore[return-value]
        except (*ARCHIVE_ERRORS, NotImplementedError) as exc:
            raise ImportZipUnsafe from exc

    return open_entry
