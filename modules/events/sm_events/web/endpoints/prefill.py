"""What the console calendar's "More options" hands the new-event editor in the URL.

``?all_day=0|1&start=&end=&title=``: wall clock in the calendar's own zone (a date, or a
date and ``HH:MM``), and a one-line title. None of it is trusted, and none of it is an
error: whatever does not check out is dropped and the editor opens with its defaults."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sm_events.core import constants
from sm_events.web.schemas._fields import single_line

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_ALL_DAY = {"0": False, "1": True}


def _wall(text: str | None) -> tuple[datetime, bool] | None:
    """A valid wall clock and whether it is a date alone; ``None`` for anything else."""
    if text is None or not (_DATE.fullmatch(text) or _DATETIME.fullmatch(text)):
        return None
    try:
        return datetime.fromisoformat(text), len(text) == len("YYYY-MM-DD")
    except ValueError:
        return None


def _times(params: Mapping[str, str]) -> dict[str, Any]:
    """Both ends or neither, agreeing with each other and with ``all_day``."""
    start, end = _wall(params.get("start")), _wall(params.get("end"))
    if start is None or end is None or start[1] != end[1]:
        return {}
    asked = params.get("all_day")
    if asked is not None and _ALL_DAY.get(asked) is not start[1]:
        return {}
    later = end[0] >= start[0] if start[1] else end[0] > start[0]
    if not later:
        return {}
    return {"all_day": start[1], "start": params["start"], "end": params["end"]}


def _title(text: str | None) -> str | None:
    if text is None or len(text) > constants.TITLE_MAX:
        return None
    try:
        single_line(text)
    except ValueError:
        return None
    return text.strip() or None


def parse_prefill(params: Mapping[str, str]) -> dict[str, Any] | None:
    found = _times(params)
    title = _title(params.get("title"))
    if not found and title is None:
        return None
    return {"all_day": None, "start": None, "end": None, **found, "title": title}
