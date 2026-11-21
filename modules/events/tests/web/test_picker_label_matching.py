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
    assert not matches_query(label, "nina@example.com", "Nina")
    assert matches_query(label, "nina@example.com", "nina@example.com")
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


ADDRESS = "nina@example.org"


@pytest.mark.parametrize("at", ["@", "\ufe6b", "\uff20"])
@pytest.mark.parametrize("gap", [" ", "\u00a0", ""])
@pytest.mark.parametrize("query", ["hidden", "nina", "example", "hid", "Nina"])
def test_label_carrying_an_address_is_never_matched_by_name(at, gap, query):
    label = f"Nina <hidden{gap}{at}{gap}example.org>"
    assert not matches_query(label, ADDRESS, query)


@pytest.mark.parametrize("at", ["@", "\ufe6b", "\uff20"])
def test_label_carrying_an_address_is_found_by_the_exact_address(at):
    label = f"Nina <hidden {at} example.org>"
    assert matches_query(label, ADDRESS, ADDRESS)
    assert matches_query(label, ADDRESS, f"  {ADDRESS.upper()} ")
    assert safe_display_name(label, ADDRESS, ADDRESS) == ADDRESS
    assert safe_display_name(label, ADDRESS, "nina") == "n***@example.org"


def test_address_first_label_is_not_searched_by_the_name_part():
    assert not matches_query("nina@example.org (Nina)", ADDRESS, "nina")
    assert not matches_query("nina@example.org (Nina)", ADDRESS, "nina@exa")


def test_address_free_label_still_matches_by_name_or_full_address():
    assert matches_query("Nina Q", ADDRESS, "ina q")
    assert matches_query("Nina Q", ADDRESS, ADDRESS)
    assert not matches_query("Nina Q", ADDRESS, "nina@exa")


def test_long_address_free_label_is_linear():
    import time

    label = "a " * 4000
    start = time.perf_counter()
    assert not matches_query(label, ADDRESS, "zzz")
    assert safe_display_name(label, ADDRESS, "zzz") == label
    # Generous: a quadratic scan of this label takes far longer than a loaded runner's jitter.
    assert time.perf_counter() - start < 1.0


def test_no_regular_expression_runs_over_labels():
    from pathlib import Path

    import sm_events.web.services.masking as masking

    assert "import re" not in Path(masking.__file__).read_text()
