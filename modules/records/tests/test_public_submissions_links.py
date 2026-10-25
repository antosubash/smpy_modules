"""The newsletter's link tokens (#101, design §4.4), and the paths around them
that must not depend on the request: the outbox, a schema misfit."""

from __future__ import annotations

import pytest
from sm_records.public_submissions import links

SECRET = "links-test-secret"
CLAIMS = {"tenant": "acme.eu:1", "type_key": "news", "uuid": "a" * 32, "nonce": "n" * 32}


def _confirm(**overrides) -> str:
    return links.sign(SECRET, links.CONFIRM, **{**CLAIMS, "exp": 2_000_000_000, **overrides})


def test_a_confirm_link_round_trips_with_a_dotted_tenant():
    link = links.parse(SECRET, links.CONFIRM, _confirm(), now=1_900_000_000)
    assert (link.tenant, link.type_key, link.uuid, link.exp) == ("acme.eu:1", "news", "a" * 32, 2e9)
    assert links.matches(SECRET, link, "n" * 32)


def test_a_confirm_link_expires():
    with pytest.raises(links.LinkInvalid) as caught:
        links.parse(SECRET, links.CONFIRM, _confirm(exp=100), now=101)
    assert caught.value.expired


@pytest.mark.parametrize(
    "token",
    [
        _confirm().replace("acme.eu:1", "globex", 1),
        _confirm().replace("news", "other", 1),
        _confirm().replace("2000000000", "2000000001", 1),
        _confirm().rsplit(".", 2)[0] + ".AAAA." + _confirm().rsplit(".", 1)[1],
        "",
        "a.b",
        "é" * 10,
    ],
)
def test_a_tampered_or_malformed_link_fails_the_gate(token):
    with pytest.raises(links.LinkInvalid):
        links.parse(SECRET, links.CONFIRM, token, now=0)


def test_the_gate_and_the_state_are_separate_checks():
    """A link minted for an earlier nonce passes the gate (no statement is
    needed to refuse it) and fails only once the record's nonce is read."""
    link = links.parse(SECRET, links.CONFIRM, _confirm(), now=0)
    assert not links.matches(SECRET, link, "rotated")
    assert not links.matches(SECRET, link, None)
    assert not links.matches("another-secret", link, "n" * 32)
    truncated = links.parse(SECRET, links.CONFIRM, _confirm()[:-1], now=0)
    assert not links.matches(SECRET, truncated, "n" * 32)


def test_an_unsubscribe_link_is_stable_and_dies_with_its_nonce():
    first = links.sign(SECRET, links.UNSUBSCRIBE, **CLAIMS)
    assert first == links.sign(SECRET, links.UNSUBSCRIBE, **CLAIMS), "no expiry, no randomness"
    link = links.parse(SECRET, links.UNSUBSCRIBE, first)
    assert link.exp is None and links.matches(SECRET, link, "n" * 32)
    assert not links.matches(SECRET, link, "m" * 32)
    with pytest.raises(links.LinkInvalid):
        links.parse(SECRET, links.CONFIRM, first), "one action's link is not the other's"


def test_the_url_carries_the_language_unsigned():
    url = links.url("https://site.example", links.CONFIRM, "t.o.k", "de")
    assert url == "https://site.example/records/submissions/confirm?t=t.o.k&l=de"
