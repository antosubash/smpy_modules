"""Retaining a host key keeps existing mail capabilities valid until removal."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sm_newsletter.core import crypto, tokens

CURRENT = "current-host-key"
RETIRED = ("retired-newer", " retired-older \t")


def signed(secret, purpose="u"):
    return tokens.sign(secret, purpose=purpose, tenant_id="org.a", campaign_id=3, send_id=9)


@pytest.fixture(autouse=True)
def retained_keys(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", json.dumps(RETIRED))


@pytest.mark.parametrize("purpose", tokens.PURPOSES)
@pytest.mark.parametrize("secret", RETIRED)
def test_retained_keys_verify_every_mail_purpose(secret, purpose):
    assert tokens.parse(CURRENT, signed(secret, purpose), purpose=purpose) == tokens.SendToken(
        "org.a", 3, 9
    )


@pytest.mark.parametrize("purpose", tokens.PURPOSES)
def test_new_tokens_use_only_the_supplied_current_key(monkeypatch, purpose):
    token = signed(CURRENT, purpose)
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "")
    assert tokens.parse(CURRENT, token, purpose=purpose) == tokens.SendToken("org.a", 3, 9)
    assert tokens.parse(RETIRED[0], token, purpose=purpose) is None


@pytest.mark.parametrize("purpose", tokens.PURPOSES)
def test_removing_retired_key_revokes_its_tokens(monkeypatch, purpose):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", RETIRED[0])
    assert tokens.parse(CURRENT, signed(RETIRED[0], purpose), purpose=purpose) is not None
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "")
    assert tokens.parse(CURRENT, signed(RETIRED[0], purpose), purpose=purpose) is None


@pytest.mark.parametrize("purpose", tokens.PURPOSES)
def test_whitespace_in_a_bare_retired_key_is_preserved(monkeypatch, purpose):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", RETIRED[1])
    assert tokens.parse(CURRENT, signed(RETIRED[1], purpose), purpose=purpose) is not None
    assert tokens.parse(CURRENT, signed(RETIRED[1].strip(), purpose), purpose=purpose) is None


def test_current_mac_never_reads_retired_configuration(monkeypatch):
    def forbidden():
        raise AssertionError("current MAC must not consult retired keys")

    monkeypatch.setattr(crypto, "previous_secrets", forbidden)
    assert tokens.parse(CURRENT, signed(CURRENT), purpose="u") is not None


@pytest.mark.parametrize(
    "config",
    ['["private-retired-key",', '["private-retired-key", 1]', '["private-retired-key", "\\ud800"]'],
)
def test_invalid_retired_configuration_refuses_fallback_safely(monkeypatch, caplog, config):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", config)
    assert tokens.parse(CURRENT, signed(CURRENT), purpose="u") is not None
    assert tokens.parse(CURRENT, signed(RETIRED[0]), purpose="u") is None
    assert "SM_SECRET_KEY_PREVIOUS" in caplog.text
    assert "private-retired-key" not in caplog.text
    assert CURRENT not in caplog.text
    assert RETIRED[0] not in caplog.text


@pytest.mark.parametrize("purpose", tokens.PURPOSES)
def test_a_retired_key_does_not_replace_a_missing_current_key(purpose):
    assert tokens.parse("", signed(RETIRED[0], purpose), purpose=purpose) is None


@pytest.mark.parametrize("purpose", tokens.PURPOSES)
def test_retained_tokens_keep_claims_purpose_and_host_tenant_bound(purpose):
    token = signed(RETIRED[0], purpose)
    app = SimpleNamespace(
        state=SimpleNamespace(sm=SimpleNamespace(settings=SimpleNamespace(secret_key=CURRENT)))
    )
    claims = tokens.verify(app, token, purpose=purpose, resolved_tenant="org.a", refused="link")
    assert claims == tokens.SendToken("org.a", 3, 9)
    assert vars(claims) == {"tenant_id": "org.a", "campaign_id": 3, "send_id": 9}
    assert (
        tokens.verify(app, token, purpose=purpose, resolved_tenant="other", refused="link") is None
    )
    for other in tokens.PURPOSES:
        if other != purpose:
            assert tokens.parse(CURRENT, token, purpose=other) is None
    parts = token.rsplit(".", 3)
    for index, replacement in enumerate(("other", "4", "10", "A" * 22)):
        tampered = parts.copy()
        tampered[index] = replacement
        assert tokens.parse(CURRENT, ".".join(tampered), purpose=purpose) is None
