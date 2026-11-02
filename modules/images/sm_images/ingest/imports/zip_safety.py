"""Inspecting an uploaded ZIP before anything of it is imported: :func:`inspect`.

Ported from the portal's ``zip_safety.py``. ``ZipFile.extractall`` is never
used. Every refusal here fails the whole archive with a constant ``code``
(:class:`ZipRejected`), and all of them are decided **before the first item
is recorded**:

1. **The end records first.** ``ZipFile`` reads the whole central directory
   into memory on open, so the entry count and directory size are read from
   the end-of-central-directory record (ZIP64 too) and capped before it is
   ever opened.
2. **The directory.** Unsafe names (``..``, absolute, drive letters,
   backslashes, NUL) are zip-slip and refuse the archive, as do symlinks (Unix
   mode in the external attributes), encrypted entries, compression other than
   stored or deflate, entries whose data overlaps (a non-recursive bomb) and
   nested archives by name.
3. **The bytes.** Every entry is decompressed once, counting what comes out:
   ``zip_max_entry_bytes`` per entry, ``zip_max_total_bytes`` in all and
   ``zip_max_ratio`` against the entry's compressed size. **The header's
   uncompressed size is never trusted**: ``zipfile`` would stop at the
   claimed size, so each entry is read through a copy of its ``ZipInfo``
   whose size is unbounded, and the counters decide. A nested archive hidden
   under an image name is refused by its magic bytes here.

Duplicate names are allowed: each entry is its own item (:class:`Entry`), in
archive order. Folders, ``__MACOSX/`` and dot-files are not entries; the root
``metadata.json`` is read into :attr:`Plan.metadata` (``zip_metadata``) and
is not an entry either - but its bytes count against the same entry, total
and ratio caps, under its own size cap too, and a second one refuses the
archive (``metadata_duplicate``). The end records are read by ``zip_eocd``.
"""

from __future__ import annotations

import copy
import itertools
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

from sm_images.ingest.imports.zip_eocd import ZipRejected, directory_bounds
from sm_images.ingest.imports.zip_metadata import parse_json

__all__ = [
    "METADATA_MAX_BYTES",
    "READ_CHUNK_BYTES",
    "Entry",
    "Limits",
    "Plan",
    "ZipRejected",
    "inspect",
    "is_unsafe_name",
    "read_entry",
]

METADATA_NAME: Final = "metadata.json"
METADATA_MAX_BYTES: Final = 16 * 1024 * 1024
RATIO_MIN_BYTES: Final = 1024 * 1024
"""The ratio is judged only past this many bytes (tiny files compress oddly)."""
CD_BYTES_PER_ENTRY: Final = 1024
READ_CHUNK_BYTES: Final = 1024 * 1024
"""Decompressed bytes read from an entry at a time."""
_UNBOUNDED: Final = 1 << 62
_ALLOWED_COMPRESSION: Final = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_ARCHIVE_SUFFIXES: Final = frozenset(
    {".zip", ".jar", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".cab"}
)
_ARCHIVE_MAGIC: Final = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"\x1f\x8b",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
    b"\xfd7zXZ\x00",
    b"\x28\xb5\x2f\xfd",
)
_DRIVE: Final = re.compile(r"^[A-Za-z]:")
_LOCAL_HEADER: Final = 30


@dataclass(frozen=True)
class Limits:
    max_entries: int
    max_entry_bytes: int
    max_total_bytes: int
    max_ratio: int

    @classmethod
    def from_settings(cls, s: Any) -> Limits:
        return cls(s.zip_max_entries, s.zip_max_entry_bytes, s.zip_max_total_bytes, s.zip_max_ratio)


@dataclass(frozen=True)
class Entry:
    index: int
    """The item's ``feature_index``: the entry's place among the entries."""
    position: int
    """Its place in ``ZipFile.infolist()``."""
    name: str
    """The full path inside the archive (``/`` separated)."""
    filename: str
    """The basename: what the image is called, and what patterns match."""


@dataclass
class Plan:
    entries: list[Entry] = field(default_factory=list)
    metadata: Any = None
    """The root ``metadata.json``, parsed (not yet validated); ``{}`` without one."""


def is_unsafe_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if "\x00" in normalized or normalized.startswith("/") or _DRIVE.match(normalized):
        return True
    return ".." in PurePosixPath(normalized).parts


def _end(info: zipfile.ZipInfo) -> int:
    """A lower bound of where the entry's data ends (no extra field counted)."""
    return info.header_offset + _LOCAL_HEADER + len(info.orig_filename) + info.compress_size


def _check_overlap(infos: list[zipfile.ZipInfo], cd_offset: int | None) -> None:
    ordered = sorted(infos, key=lambda i: i.header_offset)
    for current, following in itertools.pairwise(ordered):
        if _end(current) > following.header_offset:
            raise ZipRejected("overlapping_entries")
    if ordered and cd_offset is not None and _end(ordered[-1]) > cd_offset:
        raise ZipRejected("overlapping_entries")


def _check_directory(infos: list[zipfile.ZipInfo], cd_offset: int | None, limits: Limits) -> None:
    if len(infos) > limits.max_entries:
        raise ZipRejected("too_many_entries")
    _check_overlap(infos, cd_offset)
    for info in infos:
        if is_unsafe_name(info.filename):
            raise ZipRejected("unsafe_path")
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ZipRejected("symlink_entry")
        if info.flag_bits & 0x1:
            raise ZipRejected("encrypted_entry")
        if info.compress_type not in _ALLOWED_COMPRESSION:
            raise ZipRejected("unsupported_compression")
        suffix = PurePosixPath(info.filename.lower()).suffix
        if not info.is_dir() and suffix in _ARCHIVE_SUFFIXES:
            raise ZipRejected("nested_archive")


def _chunks(zf: zipfile.ZipFile, info: zipfile.ZipInfo):
    """The entry's real bytes: ``zipfile`` stops at the size the header claims,
    so it reads a copy whose claimed size is unbounded (the CRC still checks)."""
    wide = copy.copy(info)
    wide.file_size = _UNBOUNDED
    with zf.open(wide) as source:
        while chunk := source.read(READ_CHUNK_BYTES):
            yield chunk


def _counted(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limits: Limits, budget: int):
    """The entry's real bytes, refused as soon as they pass a cap: the entry's
    own, what is left of the archive's (``budget``), or the ratio."""
    seen = 0
    for chunk in _chunks(zf, info):
        if seen == 0 and chunk.startswith(_ARCHIVE_MAGIC):
            raise ZipRejected("nested_archive")
        seen += len(chunk)
        if seen > limits.max_entry_bytes:
            raise ZipRejected("entry_too_large")
        if seen > budget:
            raise ZipRejected("uncompressed_too_large")
        if seen >= RATIO_MIN_BYTES and seen / max(info.compress_size, 1) > limits.max_ratio:
            raise ZipRejected("suspicious_ratio")
        yield chunk


def _measure(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limits: Limits, budget: int) -> int:
    return sum(len(chunk) for chunk in _counted(zf, info, limits, budget))


def _junk(name: str) -> bool:
    path = PurePosixPath(name)
    return path.parts[0] == "__MACOSX" or path.name.startswith(".")


def _metadata(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limits: Limits, budget: int):
    """``(document, bytes)``: counted against the archive's budgets like any
    entry, and under its own size cap."""
    raw = bytearray()
    for chunk in _counted(zf, info, limits, budget):
        raw += chunk
        if len(raw) > METADATA_MAX_BYTES:
            raise ZipRejected("metadata_too_large")
    return parse_json(bytes(raw)), len(raw)


def _plan(zf: zipfile.ZipFile, limits: Limits) -> Plan:
    infos = zf.infolist()
    _check_directory(infos, getattr(zf, "start_dir", None), limits)
    plan = Plan(metadata={})
    budget = limits.max_total_bytes
    seen_metadata = False
    for position, info in enumerate(infos):
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if name == METADATA_NAME:
            if seen_metadata:
                raise ZipRejected("metadata_duplicate")
            seen_metadata = True
            plan.metadata, used = _metadata(zf, info, limits, budget)
            budget -= used
            continue
        budget -= _measure(zf, info, limits, budget)
        if not _junk(name):
            entry = Entry(len(plan.entries), position, name, PurePosixPath(name).name)
            plan.entries.append(entry)
    return plan


def inspect(path: Path, limits: Limits) -> Plan:
    """Refuse the archive (:class:`ZipRejected`) or describe its entries.
    Synchronous and CPU-bound: run it off the event loop."""
    entries, cd_size = directory_bounds(path)
    if entries > limits.max_entries or cd_size > limits.max_entries * CD_BYTES_PER_ENTRY:
        raise ZipRejected("too_many_entries")
    try:
        with zipfile.ZipFile(path) as zf:
            return _plan(zf, limits)
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        zlib.error,
        NotImplementedError,
        EOFError,
    ) as exc:
        raise ZipRejected("invalid_zip") from exc


def read_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes | None:
    """One entry's bytes, or ``None`` once it passes ``cap`` (read no further)."""
    out = bytearray()
    for chunk in _chunks(zf, info):
        out += chunk
        if len(out) > cap:
            return None
    return bytes(out)
