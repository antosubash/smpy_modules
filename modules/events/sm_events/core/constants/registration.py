"""Registration (PR 9): seats, the settings on an event, and the refusals.

The numeric bounds of the contract live here too, so a test can pin each at its edge. The
occurrence key's width is :data:`~sm_events.core.constants.OCCURRENCE_KEY_MAX` (reminders'),
the same key.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "EVENT_UNAVAILABLE",
    "INVALID_REGISTRATION_CODE",
    "INVALID_REGISTRATION_DETAIL",
    "INVALID_REGISTRATION_REASONS",
    "REGISTRATIONS_ORPHANED_CODE",
    "REGISTRATIONS_ORPHANED_DETAIL",
    "REGISTRATION_CAPACITY_MAX",
    "REGISTRATION_CLOSED",
    "REGISTRATION_COUNTS_MAX",
    "REGISTRATION_FULL",
    "REGISTRATION_HAS_SEATS_CODE",
    "REGISTRATION_HAS_SEATS_DETAIL",
    "REGISTRATION_HOLDER_MAX",
    "REGISTRATION_MODES",
    "REGISTRATION_MODE_BUILTIN",
    "REGISTRATION_MODE_EXTERNAL",
    "REGISTRATION_MODE_NONE",
    "REGISTRATION_PROVIDER_MAX",
    "REGISTRATION_STATES",
    "REGISTRATION_TARGET_MAX",
    "REGISTRATION_UNAVAILABLE_CODE",
    "REGISTRATION_UNAVAILABLE_DETAIL",
    "REGISTRATION_UPCOMING",
    "SEATS_BUSY_CODE",
    "SEATS_BUSY_DETAIL",
    "SEAT_HOLDERS_MAX",
    "SEAT_RELEASE_MAX",
    "SUMMARIES_MAX",
    "UNKNOWN_REGISTRATION_TARGET_CODE",
    "UNKNOWN_REGISTRATION_TARGET_DETAIL",
]

# What an event offers.
REGISTRATION_MODE_NONE: Final = "none"
REGISTRATION_MODE_EXTERNAL: Final = "external"
REGISTRATION_MODE_BUILTIN: Final = "builtin"
REGISTRATION_MODES: Final = (
    REGISTRATION_MODE_NONE,
    REGISTRATION_MODE_EXTERNAL,
    REGISTRATION_MODE_BUILTIN,
)

# Column widths and bounds.
REGISTRATION_PROVIDER_MAX: Final = 64
REGISTRATION_TARGET_MAX: Final = 100
REGISTRATION_HOLDER_MAX: Final = 64
"""A seat's holder: an opaque id the provider owns (records' uuid), never personal data."""
REGISTRATION_CAPACITY_MAX: Final = 100_000
SEAT_RELEASE_MAX: Final = 1000
SEAT_HOLDERS_MAX: Final = 500
SUMMARIES_MAX: Final = 200
REGISTRATION_COUNTS_MAX: Final = 100
REGISTRATION_UPCOMING: Final = 5

# What ``describe`` answers.
REGISTRATION_STATES: Final = (
    "unavailable",
    "cancelled",
    "not_open_yet",
    "closed",
    "full",
    "open",
)

# What ``admit`` refuses with (exported by the contract).
REGISTRATION_FULL: Final = "registration_full"
REGISTRATION_CLOSED: Final = "registration_closed"
EVENT_UNAVAILABLE: Final = "event_unavailable"

# Refusals of the editor's writes.
INVALID_REGISTRATION_CODE: Final = "invalid_registration"
INVALID_REGISTRATION_DETAIL: Final = "These registration settings are not valid"
INVALID_REGISTRATION_REASONS: Final = {
    "closes_before_opens": (
        "registration_closes_before_opens",
        "Registration must close after it opens",
    ),
    "time_invalid": ("registration_time_invalid", "That is not a valid date and time"),
    "url_required": ("registration_url_required", "A registration link is required"),
    "target_required": ("registration_target_required", "Choose a registration form"),
    "provider_required": ("registration_provider_required", "Choose a kind of registration"),
    "reminder_invalid": (
        "registration_reminder_invalid",
        "That reminder time is not one of the allowed lead times",
    ),
    "option_not_allowed": (
        "registration_option_not_allowed",
        "That setting does not apply to this way of registering",
    ),
}
"""Each reason for an invalid registration: its own code and wording."""
REGISTRATION_UNAVAILABLE_CODE: Final = "registration_unavailable"
REGISTRATION_UNAVAILABLE_DETAIL: Final = "Registration through this provider is not available"
UNKNOWN_REGISTRATION_TARGET_CODE: Final = "unknown_registration_target"
UNKNOWN_REGISTRATION_TARGET_DETAIL: Final = "That registration form does not exist"
REGISTRATIONS_ORPHANED_CODE: Final = "registrations_orphaned"
REGISTRATIONS_ORPHANED_DETAIL: Final = (
    "This change would leave registrations on dates that no longer exist; "
    "cancel those occurrences instead"
)
SEATS_BUSY_CODE: Final = "seats_busy"
SEATS_BUSY_DETAIL: Final = "The seats of this event are busy right now; try again"
REGISTRATION_HAS_SEATS_CODE: Final = "registration_has_seats"
REGISTRATION_HAS_SEATS_DETAIL: Final = (
    "People are registered: the registration form and mode cannot change"
)
