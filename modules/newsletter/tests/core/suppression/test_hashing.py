"""Address normalisation and hashing: the same rule records uses."""

from __future__ import annotations

import hashlib

import pytest
from sm_newsletter.core.suppression import email_hash, normalise_email


def test_hash_normalises_like_records():
    expected = hashlib.sha256(b"ada@example.org").hexdigest()
    assert email_hash(" Ada@Example.ORG ") == email_hash("ada@example.org") == expected
    assert normalise_email(" Ada@Example.ORG ") == "ada@example.org"


@pytest.mark.parametrize("bad", ["", "   ", None, 3])
def test_normalise_refuses_empty_and_non_strings(bad):
    with pytest.raises(ValueError):
        normalise_email(bad)
