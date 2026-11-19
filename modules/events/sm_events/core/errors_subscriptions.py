"""The refusals of external subscriptions (PR 10).

Kept beside :mod:`sm_events.core.errors` (near the file-size cap); they are
:class:`EventsError` subclasses, so the one installed handler renders them. None of them ever
carries the address: a ``detail`` is a fixed sentence.
"""

from __future__ import annotations

from sm_events.core import constants
from sm_events.core.errors import Conflict, EventsError, Invalid

__all__ = [
    "RefreshTooSoon",
    "SecretUnreadable",
    "SubscriptionExists",
    "SubscriptionLimit",
    "SubscriptionNotPublicCalendar",
    "UrlRefused",
]


class SubscriptionExists(Conflict):
    code = constants.SUBSCRIPTION_EXISTS_CODE
    detail = constants.SUBSCRIPTION_EXISTS_DETAIL


class SubscriptionLimit(Conflict):
    code = constants.SUBSCRIPTION_LIMIT_CODE
    detail = constants.SUBSCRIPTION_LIMIT_DETAIL


class UrlRefused(Invalid):
    """An address the policy or the guard refused. ``code`` is one of the closed set
    (``constants.URL_REFUSAL_CODES``' values) and ``detail`` its fixed sentence."""

    def __init__(self, code: str) -> None:
        if code not in constants.URL_REFUSAL_DETAIL:
            raise ValueError("a refusal code must come from the closed set")
        super().__init__(constants.URL_REFUSAL_DETAIL[code], code)


class SubscriptionNotPublicCalendar(Invalid):
    code = constants.SUBSCRIPTION_NOT_PUBLIC_CALENDAR_CODE
    detail = constants.SUBSCRIPTION_NOT_PUBLIC_CALENDAR_DETAIL


class RefreshTooSoon(EventsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 429
    code = constants.REFRESH_TOO_SOON_CODE
    detail = constants.REFRESH_TOO_SOON_DETAIL

    def __init__(self, retry_after: int) -> None:
        super().__init__()
        self.retry_after = retry_after
        self.headers = {"Retry-After": str(max(1, retry_after))}


class SecretUnreadable(Exception):  # noqa: N818 - names the condition
    """A stored secret that no key opens. Carries nothing: not the value, not its field."""
