"""The website-submission rows of the error table (#101).

Split from :mod:`sm_records.endpoints.api._error_table` for the 300-line cap.
Plain ``(status, when, body)`` triples, which that module turns into
``ErrorRow`` and merges after the rows of the same status — so
``docs/api-reference.md`` lists each status's submission rows last.
"""

from __future__ import annotations

from typing import Final

__all__ = ["SUBMISSION_ROWS"]

SUBMISSION_ROWS: Final[tuple[tuple[int, str, str], ...]] = (
    (
        400,
        "*Submissions* — a form token that does not verify, or a form sent sooner than "
        "`public_submissions_min_fill_seconds` or later than "
        "`public_submissions_token_max_age_seconds` after it was loaded",
        '`{"detail", "code": "form_expired"}` — load the form again',
    ),
    (
        403,
        "*Submissions* — an `Origin` (else `Referer`) that is neither this host, the host's "
        "`public_base_url` nor one of `public_submissions_allowed_origins`",
        '`{"detail", "code": "bad_origin"}`',
    ),
    (
        404,
        "*Submissions* — any of: unknown type, a type that does not accept submissions or has "
        "them switched off, a newsletter list, `public_submissions_enabled` off; on a "
        "multi-tenant host, no tenant resolved",
        '`{"detail": "not found"}`',
    ),
    (
        409,
        "*Submissions* — the type's schema changed after the form was loaded",
        '`{"detail", "code": "form_changed", "definition": SubmissionDefinition}`',
    ),
    (
        409,
        "*Submissions* — a `unique` value already claimed",
        '`{"detail", "code": "conflict"}`',
    ),
    (
        409,
        "A submission action on a type that is not a contact form, *Not spam* on a record "
        "outside the trash, *Resend* on a type that notifies nobody",
        '`{"detail", "code": "wrong_kind" \\| "not_in_trash" \\| "no_recipients"}`',
    ),
    (
        413,
        "*Submissions* — a body over `public_submissions_max_body_bytes`",
        '`{"detail"}` — refused from `Content-Length`, before the body is read',
    ),
    (
        415,
        "*Submissions* — a body that is not `application/json`",
        '`{"detail", "code": "unsupported_media_type"}`',
    ),
    (
        422,
        "*Submissions* — a `data` key outside the type's `public_fields`, a required consent "
        "not given, or `data` that does not satisfy the schema",
        '`{"detail", "code": "unknown_field" \\| "consent_required" \\| "invalid", "errors"}`',
    ),
    (
        429,
        "*Submissions* — over `public_submissions_rate_per_ip` or "
        "`public_submissions_type_rate`; *Resend* more than once a minute for one record",
        '`{"detail", "code": "rate_limited"}` with `Retry-After`',
    ),
)
