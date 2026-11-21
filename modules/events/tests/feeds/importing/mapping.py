"""Helpers for the mapper's tests: a file in, mapped items out."""

from __future__ import annotations

import uuid

from sm_events.feeds.importing.mapper import Mapped, map_calendar
from sm_events.feeds.importing.scan import scan

from tests.feeds.importing import corpus


def mapped(*body: str, tz: str = "Europe/Vienna", categories=None) -> Mapped:
    return map_calendar(
        scan(corpus.calendar(*body)).events, calendar_tz=tz, categories=categories or {}
    )


def one(*body: str, **kw):
    got = mapped(*body, **kw)
    assert len(got.items) == 1, [i.skip for i in got.items]
    return got.items[0]


def event(
    uid="a@x",
    *extra: str,
    start="20260701T100000Z",
    end="20260701T110000Z",
    summary="Talk",
    dtstart=None,
):
    """A VEVENT; ``summary`` and ``dtstart`` (a whole line) replace the defaults."""
    lines = corpus.vevent(uid, *extra, start=start, end=end)
    lines[4] = f"SUMMARY:{summary}"
    if dtstart is not None:
        lines[2] = dtstart
    return lines


CAT = uuid.UUID(int=7)
