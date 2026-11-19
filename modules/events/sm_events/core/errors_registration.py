"""The refusals of registration (PR 9).

Kept beside :mod:`sm_events.core.errors` (which is near the file-size cap); they are
:class:`EventsError` subclasses, so the one installed handler renders them.
"""

from __future__ import annotations

from sm_events.core import constants
from sm_events.core.errors import Conflict, Invalid

__all__ = [
    "InvalidRegistration",
    "RegistrationHasSeats",
    "RegistrationUnavailable",
    "RegistrationsOrphaned",
    "SeatsBusy",
    "UnknownRegistrationTarget",
]

_SERVICE_UNAVAILABLE = 503


class InvalidRegistration(Invalid):
    code = constants.INVALID_REGISTRATION_CODE
    detail = constants.INVALID_REGISTRATION_DETAIL


class RegistrationUnavailable(Invalid):
    """No provider is installed for the mode (422), or it did not answer in time (503)."""

    code = constants.REGISTRATION_UNAVAILABLE_CODE
    detail = constants.REGISTRATION_UNAVAILABLE_DETAIL

    def __init__(self, *args: object, timed_out: bool = False, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        if timed_out:
            self.status_code = _SERVICE_UNAVAILABLE


class UnknownRegistrationTarget(Invalid):
    code = constants.UNKNOWN_REGISTRATION_TARGET_CODE
    detail = constants.UNKNOWN_REGISTRATION_TARGET_DETAIL


class RegistrationsOrphaned(Conflict):
    """A series change would strand seats on an occurrence that stops existing."""

    code = constants.REGISTRATIONS_ORPHANED_CODE
    detail = constants.REGISTRATIONS_ORPHANED_DETAIL


class RegistrationHasSeats(Conflict):
    """The provider, target or mode cannot change while somebody holds a seat."""

    code = constants.REGISTRATION_HAS_SEATS_CODE
    detail = constants.REGISTRATION_HAS_SEATS_DETAIL


class SeatsBusy(Conflict):
    """A release could not settle its locks in order within its bounded restarts, because seats kept
    arriving at lower occurrences while it ran. Nothing was changed; **retry**: it is a 409, never a
    half-done release."""

    code = constants.SEATS_BUSY_CODE
    detail = constants.SEATS_BUSY_DETAIL
