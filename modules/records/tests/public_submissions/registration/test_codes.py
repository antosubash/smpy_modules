"""Records' spelling of events' contract values is the contract's: one table, no drift."""

from __future__ import annotations

from sm_events.contracts import registration as contract
from sm_events.core import constants as events_constants
from sm_records.public_submissions.errors import CODES
from sm_records.public_submissions.registration import codes, seats, status
from sm_records.public_submissions.registration.mail import LIVE as MAIL_LIVE


def test_the_table_covers_every_refusal_code_the_contract_exports():
    exported = {
        contract.REGISTRATION_FULL,
        contract.REGISTRATION_CLOSED,
        contract.EVENT_UNAVAILABLE,
    }
    assert set(codes.TABLE) == exported
    assert (codes.REGISTRATION_FULL, codes.REGISTRATION_CLOSED, codes.EVENT_UNAVAILABLE) == (
        contract.REGISTRATION_FULL,
        contract.REGISTRATION_CLOSED,
        contract.EVENT_UNAVAILABLE,
    )
    assert all(CODES[code] == 409 for code in exported)  # and each has a status
    assert all(entry.notice in ("full", "closed") for entry in codes.TABLE.values())


def test_every_code_events_can_refuse_with_is_in_the_table():
    refusals = {
        events_constants.REGISTRATION_FULL,
        events_constants.REGISTRATION_CLOSED,
        events_constants.EVENT_UNAVAILABLE,
    }
    assert refusals == set(codes.TABLE)
    assert codes.known("something_else") == codes.REGISTRATION_CLOSED and codes.known(None)


def test_the_release_bound_is_the_contracts():
    assert seats.integration().SEAT_RELEASE_MAX == contract.SEAT_RELEASE_MAX == 1000


def test_the_statuses_are_spelled_once():
    assert status.LIVE == (status.PENDING, status.REGISTERED) == MAIL_LIVE
    assert status.SEATED == (status.REGISTERED,)
