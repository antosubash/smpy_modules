"""Reminders (PR 8): the codes, states, names and column widths.

The numeric bounds (lead times, limits, budgets) live in :mod:`sm_events.reminders.limits`.
"""

from __future__ import annotations

from typing import Final

from sm_events.core.constants.names import MODULE_NAME

__all__ = [
    "AVAILABILITY_REASONS",
    "FOLLOW_LIMIT_CODE",
    "FOLLOW_LIMIT_DETAIL",
    "INVALID_LEAD_CODE",
    "INVALID_LEAD_DETAIL",
    "MENU_ICON_REMINDERS",
    "MENU_LABEL_KEY_REMINDERS",
    "MENU_LABEL_REMINDERS",
    "NOT_PUBLISHED_CODE",
    "NOT_PUBLISHED_DETAIL",
    "OCCURRENCE_KEY_MAX",
    "REMINDERS_UNAVAILABLE_CODE",
    "REMINDERS_UNAVAILABLE_DETAIL",
    "REMINDERS_URL",
    "REMINDER_CODE_MAX",
    "REMINDER_SEND_FAILED",
    "REMINDER_SEND_TIMEOUT",
    "REMINDER_STATES",
    "REMINDER_USER_MAX",
    "_PAGE_REMINDERS",
]

_VIEW_PREFIX = f"/admin/{MODULE_NAME.lower()}"

# Console page and sidebar entry.
_PAGE_REMINDERS: Final = f"{MODULE_NAME}/Reminders"
REMINDERS_URL: Final = f"{_VIEW_PREFIX}/reminders"
MENU_LABEL_REMINDERS: Final = "Reminders"
MENU_LABEL_KEY_REMINDERS: Final = "events.menu.reminders"
MENU_ICON_REMINDERS: Final = "bell"

# Column widths.
REMINDER_USER_MAX: Final = 64
OCCURRENCE_KEY_MAX: Final = 80
"""``"{event_id}"`` or ``"{event_id}:{original_start}"`` (PR 2's occurrence key)."""
REMINDER_CODE_MAX: Final = 32

# The ledger: a claim is ``sending``; its outcome is ``sent`` or ``failed`` and final.
REMINDER_STATES: Final = ("sending", "sent", "failed")
REMINDER_SEND_FAILED: Final = "send_failed"
REMINDER_SEND_TIMEOUT: Final = "send_timeout"

# Why reminders cannot be delivered, in the order they are checked.
AVAILABILITY_REASONS: Final = (
    "disabled",
    "no_public_base_url",
    "no_mail_transport",
    "console_mail",
    "worker_access_unavailable",
)

# Refusals.
FOLLOW_LIMIT_CODE: Final = "follow_limit"
FOLLOW_LIMIT_DETAIL: Final = "You are already following the most events reminders allow"
NOT_PUBLISHED_CODE: Final = "not_published"
NOT_PUBLISHED_DETAIL: Final = "Only a published event can be followed for reminders"
INVALID_LEAD_CODE: Final = "invalid_lead"
INVALID_LEAD_DETAIL: Final = "That is not one of the allowed reminder times"
REMINDERS_UNAVAILABLE_CODE: Final = "reminders_unavailable"
REMINDERS_UNAVAILABLE_DETAIL: Final = "Reminders cannot be delivered on this site right now"
