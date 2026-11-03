"""The form token (#101): a forged one is refused as a token error, never a 500."""

from __future__ import annotations

import pytest
from sm_records.public_submissions.tokens import TokenError, sign_form, verify_form

SECRET = "s" * 32


@pytest.mark.parametrize("token", ["abc.².n.m", "abc.1.n.é", "é.1.n.m", "", "a.b"])
def test_a_non_ascii_or_malformed_token_is_a_token_error(token: str) -> None:
    with pytest.raises(TokenError):
        verify_form(SECRET, token, "default", "contact", min_fill=0, max_age=60)


def test_a_signed_token_verifies_once_old_enough() -> None:
    token = sign_form(SECRET, "default", "contact", "abc123", now=1000)
    claims = verify_form(SECRET, token, "default", "contact", min_fill=3, max_age=60, now=1010)
    assert claims.digest == "abc123"
