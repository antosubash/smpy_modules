"""The ``.ics`` import (PR 5): its limits, states, verdicts and the codes it answers with."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

__all__ = [
    "ICS_INVALID_CODE",
    "ICS_INVALID_DETAIL",
    "IMPORT_ACTIVE_MAX",
    "IMPORT_APPLY_BATCH",
    "IMPORT_BODY_CEILING",
    "IMPORT_BUSY_CODE",
    "IMPORT_BUSY_DETAIL",
    "IMPORT_DEFAULT_BYTES",
    "IMPORT_DEFAULT_DURATION",
    "IMPORT_DESCRIPTION_MAX",
    "IMPORT_FAILURE_CODES",
    "IMPORT_FILENAME_FALLBACK",
    "IMPORT_FILENAME_MAX",
    "IMPORT_ITEM_CHUNK",
    "IMPORT_KEEP_REASONS",
    "IMPORT_LEASE",
    "IMPORT_MAX_COMPONENTS",
    "IMPORT_MAX_DEPTH",
    "IMPORT_MAX_EVENTS",
    "IMPORT_MAX_EVENT_BYTES",
    "IMPORT_MAX_EXDATES",
    "IMPORT_MAX_LINE",
    "IMPORT_MAX_LINES",
    "IMPORT_MAX_OVERRIDES",
    "IMPORT_MAX_PARAMS",
    "IMPORT_MAX_PROPERTIES",
    "IMPORT_MAX_TIMEZONES",
    "IMPORT_MIB",
    "IMPORT_MIN_BYTES",
    "IMPORT_READ_CHUNK",
    "IMPORT_SLICE_SECONDS",
    "IMPORT_STATES",
    "IMPORT_STATE_CODE",
    "IMPORT_STATE_DETAIL",
    "IMPORT_TOO_LARGE_CODE",
    "IMPORT_TOO_LARGE_DETAIL",
    "IMPORT_TTL",
    "IMPORT_UID_CHUNK",
    "IMPORT_UNTITLED",
    "ITEM_OUTCOMES",
    "ITEM_VERDICTS",
    "MENU_ICON_IMPORT",
    "MENU_LABEL_IMPORT",
    "MENU_LABEL_KEY_IMPORT",
]

MENU_LABEL_IMPORT: Final = "Import"
MENU_LABEL_KEY_IMPORT: Final = "events.menu.import"
MENU_ICON_IMPORT: Final = "upload"

IMPORT_MIN_BYTES: Final = 64 * 1024
IMPORT_DEFAULT_BYTES: Final = 5 * 1024 * 1024
IMPORT_BODY_CEILING: Final = 20 * 1024 * 1024
IMPORT_MAX_EVENTS: Final = 5000
IMPORT_MAX_COMPONENTS: Final = 20_000
IMPORT_MAX_DEPTH: Final = 3
IMPORT_MAX_TIMEZONES: Final = 100
IMPORT_MAX_PROPERTIES: Final = 500
IMPORT_MAX_LINE: Final = 65_536
IMPORT_MAX_LINES: Final = 1_000_000
"""Physical lines in a file (a 20 MiB file of empty lines would otherwise cost a list each)."""
IMPORT_MAX_PARAMS: Final = 20
IMPORT_MAX_EXDATES: Final = 1000
"""``EXDATE`` values one event may carry before it is skipped (``too_many_overrides``)."""
IMPORT_MAX_EVENT_BYTES: Final = 262_144
IMPORT_MAX_OVERRIDES: Final = 730
IMPORT_DESCRIPTION_MAX: Final = 20_000
IMPORT_ACTIVE_MAX: Final = 5
IMPORT_READ_CHUNK: Final = 64 * 1024
IMPORT_MIB: Final = 1024 * 1024
IMPORT_FILENAME_MAX: Final = 200
IMPORT_FILENAME_FALLBACK: Final = "calendar.ics"
IMPORT_UID_CHUNK: Final = 500
IMPORT_ITEM_CHUNK: Final = 500
IMPORT_APPLY_BATCH: Final = 50
IMPORT_SLICE_SECONDS: Final = 45
IMPORT_LEASE: Final = timedelta(minutes=5)
IMPORT_TTL: Final = timedelta(hours=24)
IMPORT_KEEP_REASONS: Final = 1000
IMPORT_DEFAULT_DURATION: Final = timedelta(hours=1)
IMPORT_UNTITLED: Final = "Untitled event"

IMPORT_STATES: Final = ("uploaded", "parsing", "staged", "queued", "running", "done", "failed")
ITEM_VERDICTS: Final = ("new", "update", "skip")
ITEM_OUTCOMES: Final = ("created", "updated", "unchanged", "skipped", "failed")
IMPORT_FAILURE_CODES: Final = ("ics_encoding", "ics_invalid", "too_many_events", "import_failed")

IMPORT_BUSY_CODE: Final = "import_busy"
IMPORT_BUSY_DETAIL: Final = "Too many imports are still running; wait for one to finish"
IMPORT_STATE_CODE: Final = "import_state"
IMPORT_STATE_DETAIL: Final = "The import is not in a state that allows this"
IMPORT_TOO_LARGE_CODE: Final = "import_too_large"
IMPORT_TOO_LARGE_DETAIL: Final = "The file is larger than the import limit"
ICS_INVALID_CODE: Final = "ics_invalid"
ICS_INVALID_DETAIL: Final = "The file is not a valid iCalendar file"
