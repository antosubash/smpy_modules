from __future__ import annotations

import base64

import pytest
from sm_newsletter.core import tokens

SECRET = "s3cret"


def _tok(tenant="default", c=3, s=9, secret=SECRET):
    return tokens.sign(secret, tenant_id=tenant, campaign_id=c, send_id=s)


def test_round_trip():
    assert tokens.parse(SECRET, _tok()) == tokens.SendToken("default", 3, 9)


def test_a_tenant_with_dots_round_trips():
    assert tokens.parse(SECRET, _tok("org.a")) == tokens.SendToken("org.a", 3, 9)


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_tampering_with_any_part_is_refused(index):
    parts = _tok().rsplit(".", 3)
    parts[index] = {0: "other", 1: "4", 2: "10", 3: "A" * 22}[index]
    assert tokens.parse(SECRET, ".".join(parts)) is None


@pytest.mark.parametrize("bad", ["test", "", "a.b.c.d", "é.1.2.mac", "x" * 201, None, 5])
def test_malformed_tokens_are_none(bad):
    assert tokens.parse(SECRET, bad) is None


def test_a_201_character_token_is_none():
    assert tokens.parse(SECRET, "t" * 201) is None


def test_a_token_of_exactly_max_token_characters_is_read(monkeypatch):
    """No real tenant makes one that long, so the tenant check is lifted: a
    signed token of :data:`~tokens.MAX_TOKEN` characters verifies, one more does not."""
    monkeypatch.setattr(tokens, "valid_tenant", lambda _value: True)
    tenant = "t" * (tokens.MAX_TOKEN - len(_tok(tenant="")))
    at_limit, over = _tok(tenant), _tok(tenant + "t")
    assert (len(at_limit), len(over)) == (tokens.MAX_TOKEN, tokens.MAX_TOKEN + 1)
    assert tokens.parse(SECRET, at_limit) == tokens.SendToken(tenant, 3, 9)
    assert tokens.parse(SECRET, over) is None


def test_another_secret_is_none():
    assert tokens.parse("other", _tok()) is None


def test_empty_secret():
    with pytest.raises(ValueError):
        tokens.sign("", tenant_id="default", campaign_id=1, send_id=1)
    assert tokens.parse("", _tok()) is None


def test_bad_tenant_refuses_to_sign():
    with pytest.raises(ValueError):
        tokens.sign(SECRET, tenant_id="bad tenant", campaign_id=1, send_id=1)


def test_the_mac_is_16_bytes():
    mac = _tok().rsplit(".", 1)[1]
    assert len(base64.urlsafe_b64decode(mac + "=" * (-len(mac) % 4))) == 16


def test_url_has_no_at_sign_and_joins_the_prefix():
    url = tokens.unsubscribe_url("https://x.example/", _tok())
    assert "@" not in url
    assert url.startswith("https://x.example/") and "/u/" in url


def test_ids_of_18_digits_verify_and_19_do_not():
    """The digit cap keeps ``int()`` bounded; a signed 19-digit id is still refused."""
    big = 10**17
    assert tokens.parse(SECRET, _tok(c=big, s=big)) == tokens.SendToken("default", big, big)
    assert tokens.parse(SECRET, _tok(c=10 * big, s=9)) is None
    assert tokens.parse(SECRET, _tok(c=3, s=10 * big)) is None


@pytest.mark.parametrize("raw", ["03.9", "3.09", "003.009", "+3.9"])
def test_non_canonical_ids_are_refused(raw):
    """``03`` and ``3`` would both verify: one send, one token."""
    tenant, _, _, mac = _tok().rsplit(".", 3)
    assert tokens.parse(SECRET, f"{tenant}.{raw}.{mac}") is None
