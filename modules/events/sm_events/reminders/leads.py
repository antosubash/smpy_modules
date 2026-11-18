"""Lead times: the closed set, one validation for every entry point, effective defaults.

A lead is how many minutes before an occurrence a reminder goes out, and it is one of
:data:`~sm_events.reminders.limits.REMINDER_LEADS`. Nothing else is ever stored by a write;
what a *stored* value may be (an older release's, a hand-edited setting) is handled where it is
read, by dropping it, never by refusing to load.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Final

from sm_events.core.errors_reminders import InvalidLead
from sm_events.reminders.limits import REMINDER_LEADS

if TYPE_CHECKING:
    from sm_events.core.settings import EventsSettings
    from sm_events.models import Calendar

__all__ = [
    "LEADS_INPUT_MAX",
    "effective_defaults",
    "install_defaults",
    "validate_distinct",
    "validate_leads",
]

LEADS_INPUT_MAX: Final = 16
"""Most values a request may carry: well above the set, so duplicates are forgiven, but a body
of thousands is refused before it is looked at."""


def _known(value: Any) -> bool:
    # ``True == 1``: a bool is never a lead, whatever it compares equal to.
    return type(value) is int and value in REMINDER_LEADS


def validate_leads(values: Iterable[Any]) -> tuple[int, ...]:
    """The distinct leads of ``values``, ascending. ``InvalidLead`` for any value outside the
    set or an input longer than :data:`LEADS_INPUT_MAX`."""
    given = []
    for value in values:
        given.append(value)
        if len(given) > LEADS_INPUT_MAX:
            raise InvalidLead
    if not all(_known(value) for value in given):
        raise InvalidLead
    return tuple(sorted(set(given)))


def validate_distinct(values: Iterable[Any]) -> tuple[int, ...]:
    """:func:`validate_leads`, and a duplicate is refused too (a calendar's stored list)."""
    given = list(values)
    chosen = validate_leads(given)
    if len(chosen) != len(given):
        raise InvalidLead
    return chosen


def _readable(values: Iterable[Any]) -> tuple[int, ...]:
    return tuple(sorted({value for value in values if _known(value)}))


def install_defaults(settings: EventsSettings) -> tuple[int, ...]:
    """The install-wide suggestion, stored values outside the set dropped."""
    return _readable(settings.default_reminder_minutes)


def effective_defaults(settings: EventsSettings, calendar: Calendar) -> tuple[int, ...]:
    """What "Remind me" preselects on ``calendar``: its own list when it has one (even an empty
    one), else the install-wide setting. Stored values outside the set are dropped."""
    own = calendar.default_reminder_minutes
    return install_defaults(settings) if own is None else _readable(own)
