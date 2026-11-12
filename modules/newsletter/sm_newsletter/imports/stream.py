"""One Mailchimp export file's bytes as text, a physical line at a time (R8).

Split out of :mod:`sm_newsletter.imports.mailchimp`, which re-exports
:func:`text_stream`. A bad byte or an over-long line is pinned to its line
number, never its content (R16).
"""

from __future__ import annotations

import io
from typing import BinaryIO, TextIO

from sm_newsletter.core.errors_import import ImportMalformedCsv, ImportZipUnsafe
from sm_newsletter.imports.archive import ARCHIVE_ERRORS
from sm_newsletter.imports.constants import MAX_LINE

__all__ = ["text_stream"]


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
