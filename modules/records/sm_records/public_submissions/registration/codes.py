"""The refusal codes of a registration, and what each says, in one place.

The codes are the ones ``sm_events.contracts.registration`` refuses ``admit`` with. Records must run
without events, so it spells them once here (``tests`` assert they equal the contract's, and that
this table covers every one the contract exports) instead of importing the contract at module load.
Three callers read the table: the submit route (a refusal), the confirmation (a refusal, to someone
who proved control of the address) and the mail notice sent when a submit finds the event full.
"""

from __future__ import annotations

from typing import Final, NamedTuple

__all__ = [
    "EVENT_UNAVAILABLE",
    "REGISTRATION_CLOSED",
    "REGISTRATION_FULL",
    "TABLE",
    "Refusal",
    "known",
]

REGISTRATION_FULL: Final = "registration_full"
REGISTRATION_CLOSED: Final = "registration_closed"
EVENT_UNAVAILABLE: Final = "event_unavailable"


class Refusal(NamedTuple):
    message: str
    """What the 409 says."""
    notice: str
    """Which mail notice a submit that finds this sends: ``full`` or ``closed``."""


TABLE: Final = {
    REGISTRATION_FULL: Refusal("this event is fully booked", "full"),
    REGISTRATION_CLOSED: Refusal("registration for this event is closed", "closed"),
    EVENT_UNAVAILABLE: Refusal("this event is no longer available", "closed"),
}


def known(code: str | None) -> str:
    """``code`` when it is one this table knows, else the generic ``registration_closed``."""
    return code if code in TABLE else REGISTRATION_CLOSED
