"""The public surface (PR 4): where it mounts, what it answers and how much of it."""

from __future__ import annotations

from sm_events.core.constants import MODULE_NAME

DEFAULT_PUBLIC_PREFIX = "/events"
PUBLIC_PREFIX_PATTERN = r"^[a-z0-9-]+(?:/[a-z0-9-]+)*$"
RESERVED_PREFIX_SEGMENTS = (
    "admin",
    "api",
    "assets",
    "auth",
    "docs",
    "health",
    "healthz",
    "i18n",
    "login",
    "logout",
    "metrics",
    "openapi.json",
    "redoc",
    "static",
    "users",
)
"""First path segments the framework or the host owns; a public prefix never starts with one."""
_PAGE_PUBLIC_INDEX = f"{MODULE_NAME}/PublicIndex"
_PAGE_PUBLIC_EVENT = f"{MODULE_NAME}/PublicEvent"
_PAGE_PUBLIC_NOT_FOUND = f"{MODULE_NAME}/PublicNotFound"
PUBLIC_METHODS = frozenset({"GET", "HEAD"})
PUBLIC_CACHE_SECONDS = 300
PUBLIC_LISTING_CACHE_MAX = 60
PUBLIC_SWR_SECONDS = 60
PAGE_SIZE = 20
SUB_EVENTS_MAX = 200
NEXT_OCCURRENCES = 10
NOT_FOUND_SUGGESTIONS = 3
FEED_MAX_EVENTS = 1000
FEED_MAX_COMPONENTS = 5000
FEED_DAYS_BACK = 30
FEED_DAYS_AHEAD = 366
FEED_YEARS_AHEAD = 2
"""Whole years of ``VTIMEZONE`` rules written after the current one."""
SITEMAP_MAX_URLS = 10_000
FEED_RATE = "60/minute"
PUBLIC_API_RATE = "120/minute"
ICS_MEDIA_TYPE = "text/calendar; charset=utf-8"
PRODID = "-//simple-module//events//EN"

# Path segments the public routes use, so a slug may not be one (it would lose its address).
SEGMENT_API = "api"
SEGMENT_CALENDAR_FEED = "calendar"
SEGMENT_CALENDAR = "c"
SEGMENT_PRIVATE_FEED = "feed"
SEGMENT_SITEMAP = "sitemap"
RESERVED_SLUGS = (
    SEGMENT_API,
    SEGMENT_CALENDAR,
    SEGMENT_CALENDAR_FEED,
    SEGMENT_PRIVATE_FEED,
    SEGMENT_SITEMAP,
)
SLUG_RESERVED_CODE = "slug_reserved"
SLUG_RESERVED_DETAIL = "That slug is reserved for a public address"
