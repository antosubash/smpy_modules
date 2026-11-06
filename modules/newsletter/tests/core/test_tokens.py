from __future__ import annotations

import base64

import pytest
from sm_newsletter.core import tokens

SECRET = "s3cret"


def _tok(tenant="default", c=3, s=9, secret=SECRET):
    return tokens.sign(secret, purpose="u", tenant_id=tenant, campaign_id=c, send_id=s)


def test_round_trip():
    assert tokens.parse(SECRET, _tok(), purpose="u") == tokens.SendToken("default", 3, 9)


def test_a_tenant_with_dots_round_trips():
    assert tokens.parse(SECRET, _tok("org.a"), purpose="u") == tokens.SendToken("org.a", 3, 9)


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_tampering_with_any_part_is_refused(index):
    parts = _tok().rsplit(".", 3)
    parts[index] = {0: "other", 1: "4", 2: "10", 3: "A" * 22}[index]
    assert tokens.parse(SECRET, ".".join(parts), purpose="u") is None


@pytest.mark.parametrize("bad", ["test", "", "a.b.c.d", "é.1.2.mac", "x" * 201, None, 5])
def test_malformed_tokens_are_none(bad):
    assert tokens.parse(SECRET, bad, purpose="u") is None


def test_a_201_character_token_is_none():
    assert tokens.parse(SECRET, "t" * 201, purpose="u") is None


def test_another_secret_is_none():
    assert tokens.parse("other", _tok(), purpose="u") is None


def test_empty_secret():
    with pytest.raises(ValueError):
        tokens.sign("", purpose="u", tenant_id="default", campaign_id=1, send_id=1)
    assert tokens.parse("", _tok(), purpose="u") is None


def test_bad_tenant_refuses_to_sign():
    with pytest.raises(ValueError):
        tokens.sign(SECRET, purpose="u", tenant_id="bad tenant", campaign_id=1, send_id=1)


def test_the_mac_is_16_bytes():
    mac = _tok().rsplit(".", 1)[1]
    assert len(base64.urlsafe_b64decode(mac + "=" * (-len(mac) % 4))) == 16


def test_url_has_no_at_sign_and_joins_the_prefix():
    url = tokens.unsubscribe_url("https://x.example/", _tok())
    assert "@" not in url
    assert url.startswith("https://x.example/") and "/u/" in url


@pytest.mark.parametrize("raw", ["03.9", "3.09", "003.009", "+3.9"])
def test_non_canonical_ids_are_refused(raw):
    """``03`` and ``3`` would both verify: one send, one token."""
    tenant, _, _, mac = _tok().rsplit(".", 3)
    assert tokens.parse(SECRET, f"{tenant}.{raw}.{mac}", purpose="u") is None


def _signed(purpose):
    return tokens.sign(SECRET, purpose=purpose, tenant_id="default", campaign_id=3, send_id=9)


@pytest.mark.parametrize(
    ("signed_for", "parsed_as"),
    [(a, b) for a in tokens.PURPOSES for b in tokens.PURPOSES],
)
def test_purpose_is_bound(signed_for, parsed_as):
    got = tokens.parse(SECRET, _signed(signed_for), purpose=parsed_as)
    assert (got is not None) == (signed_for == parsed_as)


def test_unknown_purpose():
    with pytest.raises(ValueError):
        tokens.sign(SECRET, purpose="x", tenant_id="default", campaign_id=3, send_id=9)  # type: ignore[arg-type]
    assert tokens.parse(SECRET, _signed("u"), purpose="x") is None  # type: ignore[arg-type]


def test_mac_message_names_the_purpose():
    import hashlib
    import hmac

    digest = hmac.new(SECRET.encode(), b"newsletter|o|default|3|9", hashlib.sha256).digest()[:16]
    mac = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert _signed("o") == f"default.3.9.{mac}"


def test_open_and_click_url_shapes():
    assert tokens.open_url("https://x.example/", "T") == "https://x.example/newsletter/o/T.gif"
    assert tokens.click_url("https://x.example/", "T", 4) == "https://x.example/newsletter/c/T/4"
