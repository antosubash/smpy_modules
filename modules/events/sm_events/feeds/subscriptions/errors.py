"""Why a subscription fetch failed: a code from a closed set, and nothing else.

A library's message, a status line, a resolved address or a body can each carry the address the
subscriber typed (a private calendar link is a bearer token) or describe the network behind the
worker. So a failure keeps only its code (and the remote's status *number*), and every
``raise`` of one drops the exception that caused it.
"""

from __future__ import annotations

from sm_events.core import constants

__all__ = ["FetchFailure"]


class FetchFailure(Exception):  # noqa: N818 - names what happened
    """``str(failure)`` is ``failure.code``, one of ``constants.SUBSCRIPTION_FAILURE_CODES``."""

    def __init__(self, code: str, *, http_status: int | None = None) -> None:
        if code not in constants.SUBSCRIPTION_FAILURE_CODES:
            raise ValueError("a failure code must come from the closed set")
        super().__init__(code)
        self.code = code
        self.http_status = http_status
