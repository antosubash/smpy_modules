"""Email masking for the share picker."""

from __future__ import annotations

import pytest
from sm_events.web.services.masking import mask_email, matches_query, safe_display_name, visible_email


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


@pytest.mark.parametrize(
    ("label", "query", "expected"),
    [
        ("Amy Tester", "my tes", True),
        ("Amy Tester", "  AMY ", True),
        ("Amy Tester", "amy@example.org", True),  # the whole address
        ("Amy Tester", "AMY@EXAMPLE.ORG", True),
        ("Amy Tester", "amy@exa", False),  # part of the address only
        ("Amy Tester", "example", False),
        ("amy@example.org", "amy@exa", False),
        ("amy@example.org", "amy", False),  # a label that is the address is no name
        ("", "amy", False),
        ("Amy", "", False),
    ],
)
def test_matches_query(label, query, expected):
    assert matches_query(label, "amy@example.org", query) is expected


@pytest.mark.parametrize(
    ("label", "query", "expected"),
    [
        ("Amy Tester", "amy", "Amy Tester"),
        ("amy@example.org", "amy", "a***@example.org"),
        ("AMY@example.org", "amy@example.org", "amy@example.org"),
        ("Amy <amy@corp.test>", "amy", "a***@example.org"),
    ],
)
def test_safe_display_name(label, query, expected):
    assert safe_display_name(label, "amy@example.org", query) == expected
