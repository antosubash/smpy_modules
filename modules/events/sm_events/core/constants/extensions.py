"""The extension registry (PR 6): bounds on plugin calls, ids, and the refusals."""

from __future__ import annotations

__all__ = [
    "BUILTIN_SOURCE_CODE",
    "BUILTIN_SOURCE_DETAIL",
    "BUILTIN_SOURCE_ICON",
    "BUILTIN_SOURCE_LABEL_KEY",
    "BUILTIN_TYPE",
    "BUILTIN_TYPE_LABEL_KEY",
    "CALENDAR_SOURCES_MAX",
    "DUPLICATE_SOURCE_CODE",
    "DUPLICATE_SOURCE_DETAIL",
    "ENTRY_POINT_GROUP",
    "EXTENSIONS_MODULE",
    "EXTRA_MAX_BYTES",
    "EXTRA_TOO_LARGE_CODE",
    "EXTRA_TOO_LARGE_DETAIL",
    "PLUGIN_ID_PATTERN",
    "PLUGIN_LANG_PATTERN",
    "PLUGIN_URL_SCHEMES",
    "SOURCES_IN_MAX",
    "SOURCE_CALLS_MAX",
    "SOURCE_CALL_HARD_MAX_ITEMS",
    "SOURCE_CALL_MAX_ITEMS",
    "SOURCE_ID_MAX",
    "SOURCE_KEY_MAX",
    "SOURCE_KEY_PATTERN",
    "SOURCE_MIN_SLICE_SECONDS",
    "SOURCE_PHASE_SECONDS",
    "SOURCE_SETTINGS_MAX_BYTES",
    "SOURCE_TIMEOUT_SECONDS",
    "SOURCE_TITLE_MAX",
    "SOURCE_UNAVAILABLE_CODE",
    "SOURCE_UNAVAILABLE_DETAIL",
    "SOURCE_URL_MAX",
    "SOURCE_WINDOW_MAX_DAYS",
    "TOO_MANY_SOURCES_CODE",
    "TOO_MANY_SOURCES_DETAIL",
    "TYPE_NOT_INSTALLED_CODE",
    "TYPE_NOT_INSTALLED_DETAIL",
    "UNKNOWN_SOURCE_CODE",
    "UNKNOWN_SOURCE_DETAIL",
]

# Discovery: a package with the ``simple_module`` entry point ships ``events_extensions.py``.
ENTRY_POINT_GROUP = "simple_module"
EXTENSIONS_MODULE = "events_extensions"

# A plugin id is ``<entry-point name>:<name>``; the built-ins have no colon.
PLUGIN_ID_PATTERN = r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_-]{0,47}$"
BUILTIN_TYPE = "event"
"""The built-in type; a test pins it equal to ``models.enums.DEFAULT_EVENT_TYPE`` (importing
that here would be a cycle: the models import the constants)."""

# One plugin call, and all the calls of one read.
SOURCE_TIMEOUT_SECONDS = 2.0
SOURCE_PHASE_SECONDS = 5.0
SOURCE_MIN_SLICE_SECONDS = 0.25
SOURCE_CALLS_MAX = 16
SOURCE_CALL_MAX_ITEMS = 500
SOURCE_WINDOW_MAX_DAYS = 400
CALENDAR_SOURCES_MAX = 8

# What a plugin may return.
SOURCE_KEY_MAX = 200
SOURCE_KEY_PATTERN = r"^[A-Za-z0-9:._@-]+$"
SOURCE_TITLE_MAX = 300
SOURCE_URL_MAX = 2000
EXTRA_MAX_BYTES = 16_384

UNKNOWN_SOURCE_CODE = "unknown_source"
UNKNOWN_SOURCE_DETAIL = "That source is not installed"
BUILTIN_SOURCE_CODE = "builtin_source"
BUILTIN_SOURCE_DETAIL = "The calendar's own events are always shown and cannot be configured"
DUPLICATE_SOURCE_CODE = "duplicate_source"
DUPLICATE_SOURCE_DETAIL = "A source can be enabled once per calendar"
TOO_MANY_SOURCES_CODE = "too_many_sources"
TOO_MANY_SOURCES_DETAIL = "Too many sources are enabled on this calendar"
EXTRA_TOO_LARGE_CODE = "extra_too_large"
EXTRA_TOO_LARGE_DETAIL = "The event type's extra data is too large"
TYPE_NOT_INSTALLED_CODE = "type_not_installed"
TYPE_NOT_INSTALLED_DETAIL = (
    "This event's type is not installed, so its extra data cannot be changed"
)
SOURCE_UNAVAILABLE_CODE = "source_unavailable"
SOURCE_UNAVAILABLE_DETAIL = "The source could not check its settings"

# The built-ins' registry entries.
BUILTIN_TYPE_LABEL_KEY = "events.types.event"
BUILTIN_SOURCE_LABEL_KEY = "events.menu.events"
BUILTIN_SOURCE_ICON = "calendar"

# Per-calendar entries.
SOURCE_SETTINGS_MAX_BYTES = 16_384
SOURCE_ID_MAX = 120
SOURCES_IN_MAX = 64
"""What a PUT body may carry before the (smaller) per-calendar cap is applied."""

# A call that hands back more than this many items is a broken source, not a busy one:
# it is refused unread (up to ``SOURCE_CALL_MAX_ITEMS`` are kept, the earliest first).
SOURCE_CALL_HARD_MAX_ITEMS = 5_000
PLUGIN_LANG_PATTERN = r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*$"
PLUGIN_URL_SCHEMES = ("http", "https")
