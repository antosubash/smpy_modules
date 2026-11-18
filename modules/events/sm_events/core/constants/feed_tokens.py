"""Private feed links (PR 5): the token's shape, its limits, and what a refusal looks like."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from sm_events.core.constants.public import SEGMENT_PRIVATE_FEED

__all__ = [
    "FEED_DENY_FLOOR_SECONDS",
    "FEED_LAST_USED_GRANULARITY",
    "FEED_PATH_SEGMENT",
    "FEED_PRIVATE_RATE",
    "FEED_REVOKED_KEPT_DAYS",
    "FEED_THROTTLE_KEYS",
    "FEED_TOKENS_PER_USER_CALENDAR",
    "FEED_TOKEN_RATE",
    "FEED_TOKEN_WINDOW_SECONDS",
    "NO_INDEX",
    "NO_REFERRER",
    "PRIVATE_FEEDS_UNAVAILABLE_CODE",
    "PRIVATE_FEEDS_UNAVAILABLE_DETAIL",
    "PRIVATE_FEED_CACHE_CONTROL",
    "PRIVATE_FEED_ERROR_BODY",
    "PRIVATE_FEED_NO_STORE",
    "PRIVATE_FEED_THROTTLED_BODY",
    "TOKEN_BODY_LENGTH",
    "TOKEN_BYTES",
    "TOKEN_HASH_LENGTH",
    "TOKEN_LABEL_MAX",
    "TOKEN_LIMIT_CODE",
    "TOKEN_LIMIT_DETAIL",
    "TOKEN_PATTERN",
    "TOKEN_PREFIX",
    "TOKEN_USER_MAX",
    "WEBCAL_SCHEME",
]

TOKEN_PREFIX: Final = "evf_"  # noqa: S105 - a public prefix, not a secret
"""Lets a secret scanner and the log filter recognise a feed token."""
TOKEN_BYTES: Final = 32
TOKEN_BODY_LENGTH: Final = 43
"""``base64url`` of 32 bytes, without padding."""
TOKEN_PATTERN: Final = rf"^{TOKEN_PREFIX}[A-Za-z0-9_-]{{{TOKEN_BODY_LENGTH}}}$"
TOKEN_HASH_LENGTH: Final = 64
"""A SHA-256 hex digest: the only thing stored."""
TOKEN_LABEL_MAX: Final = 100
TOKEN_USER_MAX: Final = 64

FEED_PATH_SEGMENT: Final = SEGMENT_PRIVATE_FEED
WEBCAL_SCHEME: Final = "webcal://"
FEED_TOKENS_PER_USER_CALENDAR: Final = 5
FEED_REVOKED_KEPT_DAYS: Final = 30
FEED_LAST_USED_GRANULARITY: Final = timedelta(hours=1)

FEED_DENY_FLOOR_SECONDS: Final = 0.25
"""Every refusal is held back until this long after the handler started, so how much work a
refusal did (no row: one statement; a row without access: several) is not observable."""

FEED_PRIVATE_RATE: Final = "30/minute"
FEED_TOKEN_RATE: Final = 20
FEED_TOKEN_WINDOW_SECONDS: Final = 600
FEED_THROTTLE_KEYS: Final = 10_000

NO_REFERRER: Final = "no-referrer"
NO_INDEX: Final = "noindex"
PRIVATE_FEED_NO_STORE: Final = "no-store"
PRIVATE_FEED_CACHE_CONTROL: Final = "private, no-store"
"""A served feed: not shareable, not stored."""
PRIVATE_FEED_ERROR_BODY: Final = b'{"detail":"Not found","code":"not_found"}'
"""The one body of every refusal (a constant, never built from the request)."""
PRIVATE_FEED_THROTTLED_BODY: Final = b'{"detail":"Too many requests","code":"rate_limited"}'

TOKEN_LIMIT_CODE: Final = "token_limit"  # noqa: S105 - an error code
TOKEN_LIMIT_DETAIL: Final = f"At most {FEED_TOKENS_PER_USER_CALENDAR} private links per calendar"
PRIVATE_FEEDS_UNAVAILABLE_CODE: Final = "private_feeds_unavailable"
PRIVATE_FEEDS_UNAVAILABLE_DETAIL: Final = "Private links are not available for this account"
