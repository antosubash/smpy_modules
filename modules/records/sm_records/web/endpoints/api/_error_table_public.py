"""The public read API's own rows of the error table (#349).

Split from :mod:`sm_records.web.endpoints.api._error_table` for the 300-line cap,
like ``_error_table_submissions``. Plain ``(status, when, body)`` triples, which
that module merges after the core rows of the same status and before the
website-submission ones.
"""

from __future__ import annotations

from typing import Final

from sm_records.web.endpoints.api._error_table_submissions import SUBMISSION_ROWS

__all__ = ["EXTRA_ROWS", "PUBLIC_ROWS"]

PUBLIC_ROWS: Final[tuple[tuple[int, str, str], ...]] = (
    (
        400,
        "*Public API* — more than 3 `filter` terms (listing and stats)",
        '`{"detail", "code": "too_many_filters"}`',
    ),
    (
        400,
        "*Public API* — more than one `contains` filter term (listing and stats)",
        '`{"detail", "code": "too_many_contains"}`',
    ),
    (
        503,
        "*Public API* — the listing or stats query ran past the Postgres statement timeout "
        "(5 s)",
        '`{"detail", "code": "query_timeout"}` — narrow the filter and try again',
    ),
)

EXTRA_ROWS: Final[tuple[tuple[int, str, str], ...]] = (*PUBLIC_ROWS, *SUBMISSION_ROWS)
"""What ``_error_table`` merges after its own rows: these, then the submission rows."""
