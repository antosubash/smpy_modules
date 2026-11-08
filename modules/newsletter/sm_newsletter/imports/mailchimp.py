"""Reading one Mailchimp export file: header, rows, tags and times (R8).

Pure: no database. Errors and row errors never repeat a cell value (R16).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO, TextIO

from email_validator import EmailNotValidError, validate_email

from sm_newsletter.core.errors_import import (
    ImportDuplicateColumn,
    ImportEmptyFile,
    ImportMalformedCsv,
    ImportNoEmailColumn,
    ImportNotUtf8,
    ImportTooManyColumns,
    ImportZipUnsafe,
)
from sm_newsletter.core.suppression import normalise_email
from sm_newsletter.imports.archive import ARCHIVE_ERRORS
from sm_newsletter.imports.constants import (
    EMAIL_HEADERS,
    IGNORED,
    MAILCHIMP_SYSTEM,
    MAX_CELL,
    MAX_COLUMNS,
    MAX_HEADER_KEY,
    MAX_LINE,
    TAGS_HEADER,
)
from sm_newsletter.imports.tags import parse_tags, tag_values

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_TIMES = {k: f"{k}_time" for k in ("optin", "confirm", "unsub", "clean")}
_PREFIXES = (
    ("nonsubscribed", IGNORED),
    ("unsubscribed", "unsubscribed"),
    ("subscribed", "subscribed"),
    ("cleaned", "cleaned"),
)


__all__ = [
    "Header", "Parsed", "RowError", "detect_kind", "header_key", "kind_by_name", "parse_tags",
    "parse_time", "read_header", "read_rows", "tag_values", "text_stream", "valid_email",
]  # fmt: skip


@dataclass(frozen=True)
class Header:
    delimiter: str
    names: list[str]
    email: int
    tags: int | None
    times: dict[str, int]
    mappable: list[int]


@dataclass(frozen=True)
class Parsed:
    line: int
    email: str
    fields: dict[int, str]
    tags: list[str]
    event_at: datetime | None
    consent_at: datetime | None


@dataclass(frozen=True)
class RowError:
    line: int
    code: str
    field: str | None = None
    """A column header key, never a value."""


def header_key(text: str) -> str:
    return text.replace("﻿", "").strip().casefold()


class _OneLine(io.RawIOBase):
    """Hands the decoder one physical line per read, so a bad byte is pinned to its line."""

    def __init__(self, binary: BinaryIO) -> None:
        self._binary = binary
        self._rest = b""
        self._line = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:  # type: ignore[no-untyped-def]
        if not self._rest:
            self._line += 1
            try:
                self._rest = self._binary.readline(MAX_LINE + 1)
            except ARCHIVE_ERRORS as exc:
                raise ImportZipUnsafe from exc
            if len(self._rest) > MAX_LINE:
                raise ImportMalformedCsv(f"The file is not valid CSV (line {self._line})")
        chunk, self._rest = self._rest[: len(buffer)], self._rest[len(buffer) :]
        buffer[: len(chunk)] = chunk
        return len(chunk)


def text_stream(binary: BinaryIO) -> TextIO:
    """UTF-8 (BOM allowed), strict; one line is read at a time."""
    return io.TextIOWrapper(
        io.BufferedReader(_OneLine(binary), buffer_size=1),
        encoding="utf-8-sig",
        errors="strict",
        newline="",
    )


def kind_by_name(name: str) -> str | None:
    """The kind a Mailchimp export file name says (``nonsubscribed_*`` is ``ignored``), else
    ``None``."""
    lowered = name.casefold()
    return next((kind for prefix, kind in _PREFIXES if lowered.startswith(prefix)), None)


def detect_kind(name: str, header: Header) -> str:
    if (named := kind_by_name(name)) is not None:
        return named
    if "unsub" in header.times:
        return "unsubscribed"
    if "clean" in header.times:
        return "cleaned"
    return "subscribed"


def valid_email(raw: str) -> str | None:
    try:
        normalised = normalise_email(raw)
        validate_email(normalised, check_deliverability=False)
    except (ValueError, EmailNotValidError):
        return None
    return normalised


def parse_time(cell: str) -> datetime | None:
    try:
        return datetime.strptime(cell.strip(), TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _lines(stream: TextIO, first: int) -> Iterator[str]:
    """The stream's lines; a decode failure or NUL byte names the line, never its content."""
    number = first - 1
    while True:
        number += 1
        try:
            line = next(stream, None)
        except UnicodeDecodeError as exc:
            raise ImportNotUtf8(f"The file is not UTF-8 text (line {number})") from exc
        if line is None:
            return
        if "\x00" in line:
            raise ImportMalformedCsv(f"The file is not valid CSV (line {number})")
        yield line


def _delimiter(line: str) -> str:
    try:
        return csv.Sniffer().sniff(line, delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def _refuse_duplicates(names: Sequence[str], keys: Sequence[str]) -> None:
    """Two columns with one header would collapse into one field (the later cell overwriting
    the earlier), offer a second TAGS column for mapping, or leave it open which address is
    imported. Different email-like headers are not duplicates: the first in ``EMAIL_HEADERS``
    order is the address. The header is named, never a cell."""
    seen: set[str] = set()
    for name, key in zip(names, keys, strict=True):
        if not key:
            continue
        if key in seen:
            shown = "".join(c for c in name.strip() if c.isprintable())
            raise ImportDuplicateColumn(f'The file has the column "{shown}" more than once')
        seen.add(key)


def read_header(stream: TextIO) -> Header:
    line = next(_lines(stream, 1), "")
    if not line.strip():
        raise ImportEmptyFile
    delimiter = _delimiter(line)
    try:
        names = next(csv.reader([line], delimiter=delimiter), [])
    except csv.Error as exc:
        raise ImportMalformedCsv("The file is not valid CSV (line 1)") from exc
    if len(names) > MAX_COLUMNS:
        raise ImportTooManyColumns
    names = [n[:MAX_HEADER_KEY] for n in names]
    keys = [header_key(n) for n in names]
    _refuse_duplicates(names, keys)
    email = next((keys.index(h) for h in EMAIL_HEADERS if h in keys), None)
    if email is None:
        raise ImportNoEmailColumn
    tags = keys.index(TAGS_HEADER) if TAGS_HEADER in keys else None
    times = {name: keys.index(key) for name, key in _TIMES.items() if key in keys}
    mappable = [
        i
        for i, key in enumerate(keys)
        if i not in (email, tags)
        and key not in MAILCHIMP_SYSTEM
        and key not in EMAIL_HEADERS
        and key
    ]
    return Header(delimiter, names, email, tags, times, mappable)


def _cell(row: Sequence[str], index: int | None) -> str:
    return row[index] if index is not None and index < len(row) else ""


def _event_time(header: Header, row: Sequence[str], kind: str) -> datetime | None:
    def at(name: str) -> datetime | None:
        return parse_time(_cell(row, header.times.get(name)))

    if kind == "unsubscribed":
        return at("unsub")
    if kind == "cleaned":
        return at("clean")
    return at("confirm") or at("optin")


def read_rows(
    stream: TextIO, header: Header, kind: str, *, blanks: bool = False
) -> Iterator[Parsed | RowError | None]:
    """The rows of one file. A blank row is skipped; with ``blanks`` it is yielded as ``None``
    instead, so a caller that must yield to its event loop can count every physical row."""
    if kind == IGNORED:
        return
    reader = csv.reader(_lines(stream, 2), delimiter=header.delimiter)
    while True:
        try:
            row = next(reader, None)
        except csv.Error as exc:
            raise ImportMalformedCsv(
                f"The file is not valid CSV (line {reader.line_num + 1})"
            ) from exc
        if row is None:
            return
        if not any(cell.strip() for cell in row):
            if blanks:
                yield None
            continue
        yield from _row(header, row, kind, reader.line_num + 1)


def _row(header: Header, row: list[str], kind: str, line: int) -> Iterator[Parsed | RowError]:
    raw_email = _cell(row, header.email)
    email = valid_email(raw_email) if len(raw_email) <= MAX_CELL else None
    if email is None:
        yield RowError(line, "invalid_email")
        return
    fields: dict[int, str] = {}
    for index in header.mappable:
        value = _cell(row, index)
        if len(value) > MAX_CELL:
            yield RowError(line, "cell_too_long", header_key(header.names[index]))
        elif value.strip():
            fields[index] = value.strip()
    tags: list[str] = []
    if header.tags is not None:
        cell = _cell(row, header.tags)
        if len(cell) > MAX_CELL:
            yield RowError(line, "cell_too_long", header_key(header.names[header.tags]))
        else:
            tags, dropped = parse_tags(cell)
            if dropped:
                yield RowError(line, "tag_invalid", header_key(header.names[header.tags]))
    consent = parse_time(_cell(row, header.times.get("optin")))
    yield Parsed(line, email, fields, tags, _event_time(header, row, kind), consent)
