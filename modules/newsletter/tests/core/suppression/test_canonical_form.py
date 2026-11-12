"""The one canonical address form behind every suppression key (#348)."""

from __future__ import annotations

import hashlib

import pytest
from sm_newsletter.core.suppression.hashing import (
    email_hash,
    legacy_hash,
    lookup_hashes,
    normalise_email,
)

from tests.support.sending import FULLWIDTH_E

LIGATURE_FF = "\ufb00"


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("a@xn--fa-hia.de", "a@fa\u00df.de"),  # IDNA 2008 keeps the sharp s
        (f"a@{FULLWIDTH_E}xample.org", "a@example.org"),  # fullwidth domain
        ("A@EXAMPLE.ORG ", "a@example.org"),
        ("a@xn--bcher-kva.de", "a@B\u00fccher.de"),
    ],
)
def test_spellings_of_one_domain_are_one_key(one, other):
    assert normalise_email(one) == normalise_email(other)
    assert email_hash(one) == email_hash(other)


@pytest.mark.parametrize(
    ("one", "other"),
    [
        (f"{LIGATURE_FF}@example.org", "ff@example.org"),  # NFKC would merge them
        ("\uff41dmin@example.org", "admin@example.org"),  # fullwidth local part
    ],
)
def test_a_folded_local_part_is_another_mailbox(one, other):
    assert normalise_email(one) != normalise_email(other)


def test_ascii_keys_are_unchanged():
    expected = hashlib.sha256(b"a@example.org").hexdigest()
    assert expected.startswith("e16bfe08be114c7b")
    assert email_hash(" A@Example.ORG ") == expected
    assert normalise_email("Stra\u00dfe@X.org") == "stra\u00dfe@x.org"  # lower(), not casefold
    assert lookup_hashes("a@example.org") == (expected,)


def test_a_non_ascii_spelling_is_also_looked_up_under_its_legacy_key():
    raw = f"b@{FULLWIDTH_E}xample.org"
    assert lookup_hashes(raw) == (email_hash(raw), legacy_hash(raw))
    assert legacy_hash(raw) == hashlib.sha256(raw.encode()).hexdigest()
