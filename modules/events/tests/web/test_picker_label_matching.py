"""Email text embedded in a display name must not become a search oracle."""

import pytest
from sm_events.web.services.masking import matches_query, safe_display_name, visible_email


@pytest.mark.parametrize("query", ["nina@exa", "ina@exam", "example.com"])
def test_email_tokens_in_display_name_are_not_searchable(query):
    assert not matches_query("Nina <nina@example.com>", "nina@example.com", query)


@pytest.mark.parametrize("at_sign", ["\uff20", "\ufe6b"])
def test_address_with_compatibility_at_sign_is_not_searchable_or_disclosed(at_sign):
    label = f"Nina <nina{at_sign}example.com>"
    assert not matches_query(label, "nina@example.com", "example.com")
    assert matches_query(label, "nina@example.com", "Nina")
    assert safe_display_name(label, "nina@example.com", "Nina") == "n***@example.com"
    assert safe_display_name(label, "nina@example.com", "nina@example.com") == "nina@example.com"


DECOMPOSED_ADDRESS = "renée@example.org"
PRECOMPOSED_ADDRESS = "renée@example.org"


def test_decomposed_query_matches_precomposed_address_and_reveals_it():
    assert matches_query("Someone", PRECOMPOSED_ADDRESS, DECOMPOSED_ADDRESS)
    assert visible_email(PRECOMPOSED_ADDRESS, DECOMPOSED_ADDRESS) == PRECOMPOSED_ADDRESS
    assert safe_display_name(PRECOMPOSED_ADDRESS, PRECOMPOSED_ADDRESS, DECOMPOSED_ADDRESS) == (
        PRECOMPOSED_ADDRESS
    )


def test_precomposed_query_matches_decomposed_stored_address():
    assert matches_query("Someone", DECOMPOSED_ADDRESS, PRECOMPOSED_ADDRESS)
    assert visible_email(DECOMPOSED_ADDRESS, PRECOMPOSED_ADDRESS) == DECOMPOSED_ADDRESS


def test_decomposed_query_matches_precomposed_name_and_the_reverse():
    assert matches_query("Renée Martin", "rm@example.org", "renée")
    assert matches_query("Renée Martin", "rm@example.org", "RENÉE")


def test_masking_is_otherwise_unchanged():
    assert visible_email(PRECOMPOSED_ADDRESS, "ren") == "r***@example.org"
    assert not matches_query("Someone", PRECOMPOSED_ADDRESS, "renée@exa")
