"""MINOR 4: the documented `401` body has to be the one that is sent.

`docs/api-reference.md` promised `{"detail": "Authentication required"}` for a
request with no session. That is the *permission dependency's* wording, and it
is unreachable on any install that runs an auth provider: the framework's
`AuthMiddleware` answers an anonymous `/api/*` request with
`{"detail": "Not authenticated"}` before a single route dependency runs.

Documentation drifts silently, so this pins the row to the literal the
installed framework actually contains — which also means the check fails if
the framework changes its wording, rather than the doc going quietly stale
again.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

_DOC = Path(__file__).resolve().parents[1] / "docs" / "api-reference.md"
_SENT = "Not authenticated"
_WRONG = "Authentication required"


def _error_table_row(status: str) -> str:
    rows = [
        line
        for line in _DOC.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| `{status}` |")
    ]
    assert rows, f"no `{status}` row in the error table"
    return "\n".join(rows)


def test_the_documented_401_is_the_body_the_framework_sends():
    row = _error_table_row("401")
    assert _SENT in row
    assert _WRONG not in row


def test_the_framework_still_sends_that_wording():
    """The other half of the pair: the doc is only right while this is."""
    try:
        from auth import middleware
    except ImportError:  # pragma: no cover - a venv without an auth provider
        pytest.skip("no auth provider installed to read the wording from")
    source = inspect.getsource(middleware)
    assert _SENT in source, "the framework's 401 wording moved; api-reference needs updating"
