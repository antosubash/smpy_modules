"""The refusal every website-submission route answers with (#101).

One exception rather than one per status: a form branches on ``code``, a
stable snake_case word, and the status follows from it. It is a
:class:`~sm_records.services.errors.RecordsError`, so the route class rolls
the request's session back like any other refusal, and the endpoint layer
renders ``extra`` and ``headers`` beside ``detail`` and ``code``
(:mod:`sm_records.endpoints.api.public_submissions_public`).
"""

from __future__ import annotations

from typing import Any

from sm_records.services.errors import RecordsError

__all__ = ["CODES", "SubmissionRefused"]

CODES: dict[str, int] = {
    "bad_origin": 403,
    "unsupported_media_type": 415,
    "rate_limited": 429,
    "form_expired": 400,
    "form_changed": 409,
    "unknown_field": 422,
    "consent_required": 422,
    "invalid": 422,
    "conflict": 409,
    "wrong_kind": 409,
    "not_in_trash": 409,
    "no_recipients": 409,
}
"""Every code and its status — what ``docs/api-reference.md`` lists."""


class SubmissionRefused(RecordsError):  # noqa: N818 - the module's naming for refusals
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = CODES[code]
        self.headers = headers or {}
        self.extra = extra
