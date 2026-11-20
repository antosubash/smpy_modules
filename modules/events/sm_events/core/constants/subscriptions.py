"""External ICS subscriptions (PR 10): bounds, states and the closed set of codes.

Every number a fetch is held to lives here, so the policy reads in one place. The codes are the
*only* thing a user is ever told about a failed fetch: a library's message, a status line, a
resolved address or a response body can each carry the address the subscriber typed (a private
calendar link is a bearer token), or map the network behind the worker, so none is kept.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from sm_events.core.constants.imports import IMPORT_FAILURE_CODES

__all__ = [
    "DNS_POOL_SIZE",
    "DNS_TIMEOUT_SECONDS",
    "FETCH_ACCEPT",
    "FETCH_CONNECT_SECONDS",
    "FETCH_MEDIA_TYPES",
    "FETCH_POOL_SECONDS",
    "FETCH_READ_SECONDS",
    "FETCH_USER_AGENT_PREFIX",
    "FETCH_WRITE_SECONDS",
    "MAX_ADDRESSES_PER_HOP",
    "REFRESH_SUBSCRIPTION",
    "REFRESH_SUBSCRIPTIONS",
    "REFRESH_TOO_SOON_CODE",
    "REFRESH_TOO_SOON_DETAIL",
    "SCAN_FAILURE_CODES",
    "SOURCE_SUBSCRIPTIONS",
    "SUBSCRIPTIONS_PER_CALENDAR",
    "SUBSCRIPTIONS_PER_TENANT",
    "SUBSCRIPTIONS_SOURCE_ICON",
    "SUBSCRIPTIONS_SOURCE_LABEL_KEY",
    "SUBSCRIPTION_CODE_MAX",
    "SUBSCRIPTION_COLOR_PATTERN",
    "SUBSCRIPTION_DELETED_KEPT_DAYS",
    "SUBSCRIPTION_ETAG_MAX",
    "SUBSCRIPTION_EXISTS_CODE",
    "SUBSCRIPTION_EXISTS_DETAIL",
    "SUBSCRIPTION_FAILURE_CODES",
    "SUBSCRIPTION_FETCH_SECONDS",
    "SUBSCRIPTION_ID_MAX",
    "SUBSCRIPTION_ITEMS_MAX",
    "SUBSCRIPTION_ITEM_LOCATION_MAX",
    "SUBSCRIPTION_ITEM_TITLE_MAX",
    "SUBSCRIPTION_ITEM_URL_MAX",
    "SUBSCRIPTION_LABEL_MAX",
    "SUBSCRIPTION_LAST_MODIFIED_MAX",
    "SUBSCRIPTION_LEASE",
    "SUBSCRIPTION_LEASE_OWNER_MAX",
    "SUBSCRIPTION_LIMIT_CODE",
    "SUBSCRIPTION_LIMIT_DETAIL",
    "SUBSCRIPTION_MAX_BACKOFF",
    "SUBSCRIPTION_MAX_CONCURRENT_FETCHES",
    "SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT",
    "SUBSCRIPTION_MAX_FAILURES",
    "SUBSCRIPTION_MAX_REDIRECTS",
    "SUBSCRIPTION_MAX_REFRESH_MINUTES",
    "SUBSCRIPTION_MIN_REFRESH_MINUTES",
    "SUBSCRIPTION_NOT_PAUSED_CODE",
    "SUBSCRIPTION_NOT_PAUSED_DETAIL",
    "SUBSCRIPTION_NOT_PUBLIC_CALENDAR_CODE",
    "SUBSCRIPTION_NOT_PUBLIC_CALENDAR_DETAIL",
    "SUBSCRIPTION_REFRESH_NOW_SECONDS",
    "SUBSCRIPTION_REFRESH_RATE",
    "SUBSCRIPTION_STATE_CONFLICT_CODE",
    "SUBSCRIPTION_STATE_CONFLICT_DETAIL",
    "SUBSCRIPTION_STATUSES",
    "SUBSCRIPTION_STATUS_MAX",
    "SUBSCRIPTION_STORE_CHUNK",
    "SUBSCRIPTION_TENANT_ITEMS_MAX",
    "SUBSCRIPTION_TICK_BYTES",
    "SUBSCRIPTION_TICK_FETCHES",
    "SUBSCRIPTION_TICK_SECONDS",
    "SUBSCRIPTION_URL_MAX",
    "URL_DISPLAY_MAX",
    "URL_REFUSAL_CODES",
    "URL_REFUSAL_DETAIL",
]

SOURCE_SUBSCRIPTIONS: Final = "subscriptions"
"""The built-in read source's id (never stored in ``events_calendar.sources``)."""
SUBSCRIPTIONS_SOURCE_LABEL_KEY: Final = "events.subscriptions.source"
SUBSCRIPTIONS_SOURCE_ICON: Final = "rss"

REFRESH_SUBSCRIPTIONS: Final = "events.refresh_subscriptions"
REFRESH_SUBSCRIPTION: Final = "events.refresh_subscription"

SUBSCRIPTION_NOT_PAUSED_CODE: Final = "subscription_not_paused"
SUBSCRIPTION_NOT_PAUSED_DETAIL: Final = "Only a paused or stopped subscription can be resumed"
SUBSCRIPTION_STATE_CONFLICT_CODE: Final = "subscription_paused"
SUBSCRIPTION_STATE_CONFLICT_DETAIL: Final = "Resume this subscription before refreshing it"

SUBSCRIPTION_STATUSES: Final = ("pending", "ok", "error", "paused", "disabled")

# The address.
SUBSCRIPTION_URL_MAX: Final = 2000
URL_DISPLAY_MAX: Final = 300
"""``scheme://host[:port]/…``: the only form of the address the API, the logs and the screen
carry. A host name is at most 253 characters."""

# One fetch.
SUBSCRIPTION_MAX_REDIRECTS: Final = 3
SUBSCRIPTION_FETCH_SECONDS: Final = 30.0
"""One absolute deadline: every hop's lookup, connect, handshake, headers and body."""
DNS_TIMEOUT_SECONDS: Final = 5.0
DNS_POOL_SIZE: Final = 4
MAX_ADDRESSES_PER_HOP: Final = 4
FETCH_CONNECT_SECONDS: Final = 5.0
FETCH_READ_SECONDS: Final = 15.0
FETCH_WRITE_SECONDS: Final = 5.0
FETCH_POOL_SECONDS: Final = 5.0
FETCH_USER_AGENT_PREFIX: Final = "SimpleModule-Events"
"""Followed by ``/<installed version>``: it names neither the site, nor a tenant, nor a person."""
FETCH_ACCEPT: Final = "text/calendar, text/plain;q=0.5"
FETCH_MEDIA_TYPES: Final = frozenset(
    {
        "text/calendar",
        "text/plain",
        "application/octet-stream",
        "application/ics",
        "text/x-vcalendar",
    }
)
"""A response's media type, when it names one. ``text/html`` above all is refused; the scanner
(PR 5's ``sniff``) is the real check, this only stops a login page early."""
SUBSCRIPTION_ETAG_MAX: Final = 200
SUBSCRIPTION_LAST_MODIFIED_MAX: Final = 64

# Schedule (Rulings 12-14).
SUBSCRIPTION_MIN_REFRESH_MINUTES: Final = 15
SUBSCRIPTION_MAX_REFRESH_MINUTES: Final = 1440
SUBSCRIPTION_MAX_BACKOFF: Final = timedelta(hours=24)
SUBSCRIPTION_MAX_FAILURES: Final = 10
SUBSCRIPTION_REFRESH_NOW_SECONDS: Final = 300
SUBSCRIPTION_REFRESH_RATE: Final = "6/minute"
"""Per signed-in user, on every subscription's refresh route (the per-subscription floor is
``SUBSCRIPTION_REFRESH_NOW_SECONDS``)."""
SUBSCRIPTION_DELETED_KEPT_DAYS: Final = 30

# The beat (Ruling 15).
SUBSCRIPTION_TICK_FETCHES: Final = 20
SUBSCRIPTION_TICK_BYTES: Final = 50 * 1024 * 1024
SUBSCRIPTION_TICK_SECONDS: Final = 45
SUBSCRIPTION_LEASE: Final = timedelta(minutes=2)
SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT: Final = 2
"""One tenant's share of those slots (a quarter): hung feeds of one tenant cannot hold the pool."""
SUBSCRIPTION_MAX_CONCURRENT_FETCHES: Final = 8
"""Install-wide ceiling on subscriptions leased (so being fetched) at once, whatever the number of
beats and workers; the excess waits for the next tick. Counted in the claim's own statement, so
it can overshoot by at most the number of claims racing at that instant."""

# Limits (Ruling 23).
SUBSCRIPTIONS_PER_CALENDAR: Final = 10
SUBSCRIPTIONS_PER_TENANT: Final = 100
SUBSCRIPTION_LABEL_MAX: Final = 100
SUBSCRIPTION_COLOR_PATTERN: Final = r"^#[0-9a-fA-F]{6}$"
SUBSCRIPTION_ITEM_TITLE_MAX: Final = 300
SUBSCRIPTION_ITEM_LOCATION_MAX: Final = 200
SUBSCRIPTION_ITEM_URL_MAX: Final = 2000

# Column widths.
SUBSCRIPTION_ID_MAX: Final = 64
SUBSCRIPTION_STATUS_MAX: Final = 16
SUBSCRIPTION_CODE_MAX: Final = 40
SUBSCRIPTION_LEASE_OWNER_MAX: Final = 32

# What a user is told about an address the guard refused. The guard raises its own short codes
# (``UnsafeURLError.code``); these are the user-facing ones. An address that resolves to a
# private range and a host that does not resolve at all are ONE answer: two answers would let
# anyone who may add a subscription ask the worker's resolver which internal names exist.
URL_REFUSAL_CODES: Final = {
    "invalid_url": "url_invalid",
    "missing_host": "url_invalid",
    "invalid_scheme": "url_scheme",
    "userinfo_not_allowed": "url_userinfo",
    "port_not_allowed": "url_port",
    "unresolvable_host": "url_unreachable",
    "non_public_address": "url_unreachable",
}
URL_REFUSAL_DETAIL: Final = {
    "url_invalid": "That is not a usable calendar address",
    "url_scheme": "The address must start with https://",
    "url_userinfo": "The address must not contain a user name or password",
    "url_port": "That port is not allowed",
    "url_unreachable": "That address cannot be used",
    "url_own_feed": "That is this site's own calendar feed, which cannot be subscribed to",
}

# What a feed may hold.
SUBSCRIPTION_ITEMS_MAX: Final = 5000
"""Events kept per subscription (the scanner already refuses a file with more VEVENTs)."""
SUBSCRIPTION_TENANT_ITEMS_MAX: Final = 50_000
"""Events kept per tenant across every subscription: more fails the fetch (``too_many_events``)
and keeps what was there."""
SUBSCRIPTION_STORE_CHUNK: Final = 500

SCAN_FAILURE_CODES: Final = tuple(
    code
    for code in IMPORT_FAILURE_CODES
    if code not in ("import_failed", "importer_gone", "rights_expired")
)
"""The scanner's and mapper's whole-file failures (PR 5): a subscription fails with the same
code."""

# Why a fetch failed: stored in ``error_code``, shown translated, never a message.
SUBSCRIPTION_FAILURE_CODES: Final = (
    *dict.fromkeys(URL_REFUSAL_CODES.values()),
    "url_own_feed",
    "url_unreadable",
    "too_many_redirects",
    "insecure_redirect",
    "timeout",
    "connect_failed",
    "tls_failed",
    "http_status",
    "gone",
    "too_large",
    "unsupported_encoding",
    "unexpected_content_type",
    *SCAN_FAILURE_CODES,
    "internal",
)

SUBSCRIPTION_EXISTS_CODE: Final = "subscription_exists"
SUBSCRIPTION_EXISTS_DETAIL: Final = "This calendar already has a subscription to that address"
SUBSCRIPTION_LIMIT_CODE: Final = "subscription_limit"
SUBSCRIPTION_LIMIT_DETAIL: Final = "Too many subscriptions"
SUBSCRIPTION_NOT_PUBLIC_CALENDAR_CODE: Final = "subscription_not_public_calendar"
SUBSCRIPTION_NOT_PUBLIC_CALENDAR_DETAIL: Final = (
    "A subscription can be shown on the public site only on a public calendar"
)
REFRESH_TOO_SOON_CODE: Final = "refresh_too_soon"
REFRESH_TOO_SOON_DETAIL: Final = "This subscription was refreshed a moment ago"
