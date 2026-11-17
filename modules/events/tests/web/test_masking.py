"""Email masking for the share picker."""

from __future__ import annotations

import pytest
from sm_events.web.services.masking import mask_email, visible_email


def test_exact_match_gives_the_full_address():
    assert visible_email("amy@example.org", "amy@example.org") == "amy@example.org"


def test_mixed_case_exact_match():
    assert visible_email("Amy@Example.org", "  aMY@example.ORG ") == "Amy@Example.org"


def test_name_query_gives_the_masked_address():
    assert visible_email("amy@example.org", "amy") == "a***@example.org"


@pytest.mark.parametrize("bad", ["nodomain", "@example.org", "", "@"])
def test_malformed_address_is_fully_masked(bad):
    assert mask_email(bad) == "***"
    assert visible_email(bad, "xyz") == "***"
