"""Map one transport result to what the dispatcher does with the row (ruling S4).

Pure: no I/O, no clock. Only a ``5.1.x`` refusal at RCPT is a bounce (spec
"Sending" 4), so a quota or policy refusal never suppresses a subscriber; every
other refusal pauses the campaign for an admin to look at. ``skip`` is never
returned here: the dispatcher uses it for a row it passed over without an SMTP
call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sm_newsletter.core import constants
from sm_newsletter.sending.transport.base import DeliveryResult

Action = Literal["sent", "retry", "bounce", "pause", "fail", "unknown", "skip"]

_ENHANCED = re.compile(r"^\s*(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\d)")
_SERVICE_UNAVAILABLE = 421


@dataclass(frozen=True)
class Verdict:
    action: Action
    stop_tick: bool
    error_kind: str | None = None  # constants.ERROR_*
    pause_code: str | None = None  # constants.PAUSE_*


def enhanced_code(detail: str) -> tuple[int, int, int] | None:
    """A leading RFC 3463 ``X.Y.Z`` status of a reply text, or ``None``."""
    m = _ENHANCED.match(detail)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _pause(code: str) -> Verdict:
    return Verdict("pause", True, pause_code=code)


def classify(result: DeliveryResult) -> Verdict:
    outcome = result.outcome
    if outcome == "accepted":
        return Verdict("sent", False)
    if outcome == "unknown":
        return Verdict("unknown", False, error_kind=constants.ERROR_OUTCOME_UNKNOWN)
    if outcome == "failed":
        if result.stage == "auth":
            return _pause(constants.PAUSE_SMTP_AUTH)
        return Verdict("retry", True)
    code = result.code
    if code is None:
        return Verdict("fail", False, error_kind=constants.ERROR_INVALID_MESSAGE)
    enhanced = enhanced_code(result.detail)
    if 400 <= code < 500:
        quota = code == _SERVICE_UNAVAILABLE or (enhanced is not None and enhanced[:2] == (4, 7))
        return Verdict("retry", quota)
    if 500 <= code < 600 and result.stage == "rcpt" and enhanced and enhanced[:2] == (5, 1):
        return Verdict("bounce", False, error_kind=constants.ERROR_HARD_BOUNCE)
    return _pause(constants.PAUSE_SMTP_REJECTED)
