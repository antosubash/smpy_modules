"""The S4 table: one pure function from a transport result to a verdict."""

import pytest
from sm_newsletter.core import constants
from sm_newsletter.sending.classify import Verdict, classify, enhanced_code
from sm_newsletter.sending.transport.base import DeliveryResult


def _r(outcome, code=None, detail="", stage=None):
    return DeliveryResult(outcome, code, detail, stage)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_r("accepted", 250, "2.0.0 Queued", "data"), Verdict("sent", False)),
        (
            _r("unknown", None, "connection lost", "data"),
            Verdict("unknown", False, error_kind=constants.ERROR_OUTCOME_UNKNOWN),
        ),
        (_r("failed", None, "lost", "connect"), Verdict("retry", True)),
        (_r("failed", None, "lost", "rcpt"), Verdict("retry", True)),
        (
            _r("failed", None, "auth", "auth"),
            Verdict("pause", True, pause_code=constants.PAUSE_SMTP_AUTH),
        ),
        (
            _r("rejected", None, "a header value is not valid"),
            Verdict("fail", False, error_kind=constants.ERROR_INVALID_MESSAGE),
        ),
        (_r("rejected", 451, "4.3.0 Try again", "data"), Verdict("retry", False)),
        (_r("rejected", 421, "4.7.0 Try again later", "mail"), Verdict("retry", True)),
        (_r("rejected", 450, "4.7.1 quota", "rcpt"), Verdict("retry", True)),
        (_r("rejected", 421, "service unavailable", "mail"), Verdict("retry", True)),
        (_r("rejected", 450, "4.2.1 mailbox busy", "rcpt"), Verdict("retry", False)),
        (
            _r("rejected", 550, "5.1.1 No such user", "rcpt"),
            Verdict("bounce", False, error_kind=constants.ERROR_HARD_BOUNCE),
        ),
        (
            _r("rejected", 553, "5.1.3 bad address", "rcpt"),
            Verdict("bounce", False, error_kind=constants.ERROR_HARD_BOUNCE),
        ),
        (
            _r("rejected", 550, "5.1.1 No such user", "mail"),
            Verdict("pause", True, pause_code=constants.PAUSE_SMTP_REJECTED),
        ),
        (
            _r("rejected", 550, "5.1.1 x", "data"),
            Verdict("pause", True, pause_code=constants.PAUSE_SMTP_REJECTED),
        ),
        (
            _r("rejected", 550, "5.7.1 relay denied", "rcpt"),
            Verdict("pause", True, pause_code=constants.PAUSE_SMTP_REJECTED),
        ),
        (
            _r("rejected", 554, "5.4.5 Daily sending quota exceeded", "data"),
            Verdict("pause", True, pause_code=constants.PAUSE_SMTP_REJECTED),
        ),
        (
            _r("rejected", 550, "No such user", "rcpt"),
            Verdict("pause", True, pause_code=constants.PAUSE_SMTP_REJECTED),
        ),
        (
            _r("rejected", 250, "odd", "rcpt"),
            Verdict("pause", True, pause_code=constants.PAUSE_SMTP_REJECTED),
        ),
    ],
)
def test_classify(result, expected):
    assert classify(result) == expected


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (" 5.1.1 x", (5, 1, 1)),
        ("4.7.0 Try again", (4, 7, 0)),
        ("5.1", None),
        ("", None),
        ("5.1.1000", None),
        ("No such 5.1.1", None),
    ],
)
def test_enhanced_code(detail, expected):
    assert enhanced_code(detail) == expected
