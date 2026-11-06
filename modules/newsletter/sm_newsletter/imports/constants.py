"""Limits, states and column vocabularies of the Mailchimp import.

Constants, not settings: nothing here is something an operator tunes (R7).
"""

from __future__ import annotations

from datetime import timedelta

MiB = 1024 * 1024

MAX_UPLOAD_BYTES = 50 * MiB
"""Registered with ``register_body_limits`` (+1 MiB for multipart framing)."""
MAX_FILES = 4
"""Parts in one upload, or a single ZIP."""
MAX_ZIP_ENTRIES = 16
MAX_ENTRY_BYTES = 200 * MiB
"""Declared, uncompressed."""
MAX_TOTAL_BYTES = 400 * MiB
MAX_RATIO = 200
MAX_ROWS = 250_000
"""Staged rows in all."""
MAX_COLUMNS = 200
MAX_CELL = 4096
"""Characters."""
MAX_LINE = 4 * MiB
"""Bytes in one physical line. MAX_COLUMNS x MAX_CELL is 800k characters, 3.2 MiB even if every
character took four bytes, so this admits any row the other limits admit and nothing larger."""
MAX_HEADER_KEY = 200
"""Characters of a header kept in a field key or a row error."""
MAX_TAGS_PER_ROW = 50
MAX_TAG_LEN = 100
MAX_NEW_TAGS = 500
KEEP_ERRORS = 1000
STAGED_TTL = timedelta(hours=24)

STAGED, QUEUED, RUNNING, DONE, FAILED = "staged", "queued", "running", "done", "failed"
STATES = (STAGED, QUEUED, RUNNING, DONE, FAILED)

KINDS = ("subscribed", "unsubscribed", "cleaned")
IGNORED = "ignored"
KIND_ORDER = {"cleaned": 0, "unsubscribed": 1, "subscribed": 2}
"""Precedence when one address is in several files (R3)."""

EMAIL_HEADERS = (
    "email address",
    "email",
    "e-mail",
    "e-mail address",
    "e-mail-adresse",
    "email_address",
)
NAME_DEFAULTS = {
    "first_name": ("first name", "fname", "vorname"),
    "last_name": ("last name", "lname", "nachname"),
}
TAGS_HEADER = "tags"

MAILCHIMP_SYSTEM = frozenset(
    {
        "member_rating",
        "optin_time",
        "optin_ip",
        "confirm_time",
        "confirm_ip",
        "latitude",
        "longitude",
        "gmtoff",
        "dstoff",
        "timezone",
        "cc",
        "region",
        "last_changed",
        "leid",
        "euid",
        "notes",
        "unsub_time",
        "unsub_campaign_title",
        "unsub_campaign_id",
        "unsub_reason",
        "unsub_reason_other",
        "clean_time",
        "clean_campaign_title",
        "clean_campaign_id",
    }
)
"""Mailchimp's own columns: never offered for mapping."""

BATCH_SIZE = 200
SLICE_SECONDS = 45
LEASE = timedelta(minutes=5)
STAGE_CHUNK = 1000

ROW_ERROR_CODES = (
    "invalid_email",
    "cell_too_long",
    "tag_invalid",
    "invalid_value",
    "record_refused",
    "tags_unavailable",
)
