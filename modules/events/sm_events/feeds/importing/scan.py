"""The one pass over an uploaded file, with every bound checked as it goes (Ruling 20).

Nothing here interprets a value: it decodes, unfolds, splits content lines and counts. A file
that breaks a bound fails the whole import with a code and *which* bound (never a value from
the file), in work and memory proportional to the file's size, which is itself capped before
this runs.

Bounds, all from :mod:`sm_events.core.constants`. **File-level** (the whole import fails, with a
code that names the limit): bytes, physical lines, an unfolded line, nesting depth, components of
any kind, ``VEVENT`` count, ``VTIMEZONE`` count and properties in a non-event component.
**Per-event** (that event is skipped, the rest import): properties, parameters per line, bytes
and attendees of one ``VEVENT``; the rest of such an event is counted and discarded unread.
Strict UTF-8 (a BOM is dropped); CRLF, LF and CR all end a line; a NUL byte, content before
``BEGIN:VCALENDAR``, a
second ``VCALENDAR``, anything after its ``END`` and unbalanced or mismatched ``BEGIN``/``END``
fail.

**This is the only parser.** A ``VEVENT``'s properties are kept as text (:class:`Prop`); every
other component (a ``VTIMEZONE`` with its observances, a ``VALARM`` with its ``ATTACH``) is
counted and dropped without its properties being read, so nothing in it is fetched, evaluated or
resolved.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from sm_events.core import constants
from sm_events.core.errors import ImportFailure

__all__ = ["Prop", "RawEvent", "Scanned", "scan", "sniff"]

_BOM: Final = "﻿"
_NAME: Final = re.compile(r"[A-Za-z0-9-]{1,40}")
_HEADER: Final = re.compile(
    r'(?:[A-Za-z0-9-]+\.)?([A-Za-z0-9-]+)((?:;[A-Za-z0-9-]{1,40}=(?:"[^"]*"|[^";:])*)*):'
)
_NAME_MAX: Final = 40
_PARAM: Final = re.compile(r'[;]([A-Za-z0-9-]+)=((?:"[^"]*"|[^";:])*)')
_SNIFF_HEAD: Final = 4096


@dataclass(frozen=True)
class Prop:
    """One content line of a ``VEVENT``: upper-case name, upper-case parameter names (values as
    written, quotes removed) and the raw value (still TEXT-escaped)."""

    name: str
    params: Mapping[str, str]
    value: str


@dataclass
class RawEvent:
    position: int = 0
    """1-based place among the file's top-level ``VEVENT`` components."""
    refused: str | None = None
    """Set when the event broke a **per-event** bound: its reason code (a skip). The rest of its
    body is counted and discarded unread, so only ``UID`` and ``SUMMARY`` (read before it broke
    the bound) remain in :attr:`props`."""
    props: list[Prop] = field(default_factory=list)
    children: Counter[str] = field(default_factory=Counter)
    """Components nested in the event (``VALARM``): counted for the report, never read."""


@dataclass(frozen=True)
class Scanned:
    events: tuple[RawEvent, ...]
    components: int
    timezones: int


def _fail(bound: str, code: str = constants.ICS_INVALID_CODE) -> ImportFailure:
    """A whole-file failure. ``ics_invalid`` is only for a file that is not a well-formed
    calendar; a limit has a code of its own that says which."""
    return ImportFailure(code, bound)


def sniff(head: bytes) -> bool:
    """Is the first non-blank line ``BEGIN:VCALENDAR``? The upload's quick check."""
    text = head[:_SNIFF_HEAD].decode("utf-8", errors="ignore").removeprefix(_BOM)
    for line in text.replace("\r", "\n").split("\n"):
        if line.strip():
            return line.strip().upper() == "BEGIN:VCALENDAR"
    return False


_BOM_BYTES: Final = _BOM.encode("utf-8")
_FOLD: Final = (b" ", b"\t")


def _checked(data: bytes) -> bytes:
    if len(data) > constants.IMPORT_BODY_CEILING:
        raise _fail("bytes", "file_too_large")
    if b"\x00" in data:
        raise _fail("nul")
    return data.removeprefix(_BOM_BYTES)


def _logical_lines(data: bytes):
    """Lines unfolded on **bytes** (RFC 5545 section 3.1: a fold may split a multi-byte
    character, so decoding comes after), each measured as it grows, then decoded one at a time.
    An unfolded line over the bound fails before it is joined; bytes that are not UTF-8 are
    ``ics_encoding``."""
    raw = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if raw.count(b"\n") + 1 > constants.IMPORT_MAX_LINES:
        raise _fail("lines", "too_many_lines")
    parts: list[bytes] = []
    size = 0

    def decoded() -> str:
        try:
            return b"".join(parts).decode("utf-8")
        except UnicodeDecodeError:
            raise ImportFailure("ics_encoding", "utf8") from None

    for physical in raw.split(b"\n"):
        if physical[:1] in _FOLD and parts:
            size += len(physical) - 1
            if size > constants.IMPORT_MAX_LINE:
                raise _fail("line_length", "line_too_long")
            parts.append(physical[1:])
            continue
        if parts:
            yield decoded(), size
        size = len(physical)
        if size > constants.IMPORT_MAX_LINE:
            raise _fail("line_length", "line_too_long")
        parts = [physical]
    if parts:
        yield decoded(), size


def _split(line: str) -> tuple[str, dict[str, str], str, bool] | None:
    """``(name, params, value, too_many_params)``; ``None`` for a line to ignore (a property name
    over 40 characters). A property **group** (``item1.SUMMARY``, Apple) is not part of the
    name. With too many parameters the line is not read further: the caller refuses its
    event."""
    found = _HEADER.match(line)
    if found is None:
        raise _fail("syntax")
    if len(found.group(1)) > _NAME_MAX:
        return None
    if found.group(2).count(";") > constants.IMPORT_MAX_PARAMS:
        return found.group(1).upper(), {}, "", True
    params = {key.upper(): value.strip('"') for key, value in _PARAM.findall(found.group(2) or "")}
    return found.group(1).upper(), params, line[found.end() :], False


class _State:
    """The walk's counters; a method per kind of line keeps :func:`scan` readable."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.props: list[int] = []
        self.events: list[RawEvent] = []
        self.current: RawEvent | None = None
        self.event_bytes = 0
        self.attendees = 0
        self.components = 0
        self.timezones = 0
        self.position = 0
        self.opened = False
        self.closed = False

    def refuse(self, code: str) -> None:
        """The current event broke a per-event bound: skip it, keep looking for its ``END``."""
        event = self.current
        if event is None or event.refused is not None:
            return
        event.refused = code
        event.props = [p for p in event.props if p.name in ("UID", "SUMMARY")]

    def begin(self, name: str) -> None:
        if not self.stack:
            if name != "VCALENDAR" or self.opened:
                raise _fail("vcalendar")
            self.opened = True
        elif name == "VCALENDAR":
            raise _fail("vcalendar")
        else:
            self.components += 1
            if self.components > constants.IMPORT_MAX_COMPONENTS:
                raise _fail("components", "too_many_components")
        if len(self.stack) + 1 > constants.IMPORT_MAX_DEPTH:
            raise _fail("depth", "too_deep")
        if name == "VTIMEZONE":
            self.timezones += 1
            if self.timezones > constants.IMPORT_MAX_TIMEZONES:
                raise _fail("timezones", "too_many_timezones")
        if name == "VEVENT" and self.stack == ["VCALENDAR"]:
            if len(self.events) >= constants.IMPORT_MAX_EVENTS:
                raise _fail("events", "too_many_events")
            self.position += 1
            self.current = RawEvent(position=self.position)
            self.event_bytes = self.attendees = 0
        elif self.current is not None:
            self.current.children[name] += 1
        self.stack.append(name)
        self.props.append(0)

    def end(self, name: str) -> None:
        if not self.stack or self.stack[-1] != name:
            raise _fail("unbalanced")
        self.stack.pop()
        self.props.pop()
        if name == "VEVENT" and self.stack == ["VCALENDAR"] and self.current is not None:
            self.events.append(self.current)
            self.current = None
        if not self.stack:
            self.closed = True

    def prop(self, name: str, params: dict[str, str], value: str, size: int) -> None:
        if not self.stack:
            raise _fail("outside")
        event = self.current
        if event is not None and event.refused is not None:
            return  # counted by the line and component bounds, never read
        self.props[-1] += 1
        if self.props[-1] > constants.IMPORT_MAX_PROPERTIES:
            if event is None:  # a VTIMEZONE's or a calendar-level component's
                raise _fail("properties", "component_too_large")
            self.refuse("too_many_properties")
            return
        if event is None:
            return  # counted, never read
        self.event_bytes += size
        if self.event_bytes > constants.IMPORT_MAX_EVENT_BYTES:
            self.refuse("event_too_large")
            return
        if self.stack == ["VCALENDAR", "VEVENT"]:
            if name == "ATTENDEE":
                self.attendees += 1
                if self.attendees > constants.IMPORT_MAX_ATTENDEES:
                    self.refuse("too_many_attendees")
                    return
            event.props.append(Prop(name, params, value))


def scan(data: bytes) -> Scanned:
    """Everything the file holds that an import may use, or an :class:`ImportFailure`
    naming the bound that tripped: ``ics_encoding``, ``ics_invalid`` (not a well-formed calendar)
    or the code of a file-level limit. A **per-event** limit never fails the file: that event is
    returned with :attr:`RawEvent.refused` set."""
    state = _State()
    first = True
    for line, size in _logical_lines(_checked(data)):
        if not line.strip():
            continue
        refused = state.current is not None and state.current.refused is not None
        if refused and not line[:6].upper().startswith(("BEGIN:", "END:")):
            continue  # the rest of an event that broke a bound: no header parse, no storage
        parsed = _split(line)
        if parsed is None:
            continue
        name, params, value, over = parsed
        if over and name not in ("BEGIN", "END"):
            state.refuse("too_many_parameters")
            continue
        if first:
            first = False
            if (name, value.strip().upper()) != ("BEGIN", "VCALENDAR"):
                raise _fail("first_line")
        if state.closed:
            raise _fail("trailing")
        if name == "BEGIN":
            if not _NAME.fullmatch(value.strip()):
                raise _fail("syntax")
            state.begin(value.strip().upper())
        elif name == "END":
            state.end(value.strip().upper())
        else:
            state.prop(name, params, value, size)
    if state.stack or not state.opened:
        raise _fail("unterminated")
    return Scanned(tuple(state.events), state.components, state.timezones)
