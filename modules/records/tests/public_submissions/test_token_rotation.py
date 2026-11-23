"""Retained keys preserve capabilities without weakening their binding or age."""

import json

import pytest
from sm_records.public_submissions import links
from sm_records.public_submissions.tokens import TokenError, sign_form, verify_form

CURRENT = "current-records-key"
OLD = " retired-records-key "
OLDER = "older-records-key"
CLAIMS = {"tenant": "acme.eu:1", "type_key": "news", "uuid": "a" * 32, "nonce": "n" * 32}


def form(secret=OLD, **kwargs):
    return sign_form(secret, "acme.eu:1", "news", "abc123", now=1000, **kwargs)


def verify(token, **kwargs):
    return verify_form(
        CURRENT,
        token,
        kwargs.pop("tenant", "acme.eu:1"),
        kwargs.pop("type_key", "news"),
        min_fill=3,
        max_age=60,
        now=kwargs.pop("now", 1010),
        **kwargs,
    )


def mailed(secret, action):
    return links.sign(secret, action, **CLAIMS, exp=1060)


@pytest.mark.parametrize("previous", [OLD, json.dumps(["unused", OLD]), json.dumps([OLD, OLDER])])
def test_old_forms_survive_retained_keys_verbatim(monkeypatch, previous):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", previous)
    claims = verify(form())
    assert (claims.digest, claims.issued) == ("abc123", 1000)


@pytest.mark.parametrize("now", [1002, 1061])
def test_old_form_still_obeys_minimum_fill_and_maximum_age(monkeypatch, now):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", OLD)
    with pytest.raises(TokenError):
        verify(form(), now=now)
    assert verify(form(), now=1003).issued == 1000
    assert verify(form(), now=1060).issued == 1000


@pytest.mark.parametrize("changes", [{"tenant": "other"}, {"type_key": "other"}])
def test_old_form_remains_bound_to_tenant_and_type(monkeypatch, changes):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", OLD)
    with pytest.raises(TokenError):
        verify(form(), **changes)
    with pytest.raises(TokenError):
        verify(form().replace("abc123", "def456"))


@pytest.mark.parametrize("action", [links.CONFIRM, links.UNSUBSCRIBE])
@pytest.mark.parametrize("secret", [OLD, OLDER])
def test_links_survive_multiple_rotations_and_keep_nonce_binding(monkeypatch, action, secret):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", json.dumps([OLD, OLDER]))
    token = mailed(secret, action)
    link = links.parse(CURRENT, action, token, now=1050)
    assert (link.tenant, link.type_key, link.uuid) == ("acme.eu:1", "news", "a" * 32)
    assert links.matches(CURRENT, link, CLAIMS["nonce"])
    assert not links.matches(CURRENT, link, "rotated-nonce")
    with pytest.raises(links.LinkInvalid):
        links.parse(CURRENT, action, token.replace("acme.eu:1", "other"), now=1050)
    with pytest.raises(links.LinkInvalid):
        links.parse(CURRENT, action, token.replace(".news.", ".other."), now=1050)
    other = links.UNSUBSCRIBE if action == links.CONFIRM else links.CONFIRM
    with pytest.raises(links.LinkInvalid):
        links.parse(CURRENT, other, token, now=1050)


def test_retained_confirmation_expiry_is_unchanged(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", OLD)
    assert links.parse(CURRENT, links.CONFIRM, mailed(OLD, links.CONFIRM), now=1060).exp == 1060
    with pytest.raises(links.LinkInvalid) as error:
        links.parse(CURRENT, links.CONFIRM, mailed(OLD, links.CONFIRM), now=1061)
    assert error.value.expired


@pytest.mark.parametrize("action", [links.CONFIRM, links.UNSUBSCRIBE])
def test_gate_and_state_cannot_be_spliced_from_different_keys(monkeypatch, action):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", OLD)
    current, retired = mailed(CURRENT, action), mailed(OLD, action)
    for gate_token, state_token in [(current, retired), (retired, current)]:
        spliced = gate_token.rsplit(".", 1)[0] + "." + state_token.rsplit(".", 1)[1]
        link = links.parse(CURRENT, action, spliced, now=1050)
        assert not links.matches(CURRENT, link, CLAIMS["nonce"])


def test_new_forms_and_links_are_signed_only_with_current_key(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", OLD)
    token = form(CURRENT)
    mailed_tokens = {
        action: mailed(CURRENT, action) for action in (links.CONFIRM, links.UNSUBSCRIBE)
    }
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "")
    assert verify(token).digest == "abc123"
    with pytest.raises(TokenError):
        verify_form(OLD, token, "acme.eu:1", "news", min_fill=0, max_age=60, now=1010)
    for action, token in mailed_tokens.items():
        assert links.matches(CURRENT, links.parse(CURRENT, action, token, now=1050), "n" * 32)
        with pytest.raises(links.LinkInvalid):
            links.parse(OLD, action, token, now=1050)


def test_removing_retired_key_revokes_issued_forms_and_links(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "")
    with pytest.raises(TokenError):
        verify(form())
    for action in (links.CONFIRM, links.UNSUBSCRIBE):
        with pytest.raises(links.LinkInvalid):
            links.parse(CURRENT, action, mailed(OLD, action), now=1050)


@pytest.mark.parametrize("previous", ['["private-retired-key",', "[7]", '["\\ud800"]'])
def test_bad_previous_config_refuses_fallback_without_breaking_current(
    monkeypatch, caplog, previous
):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", previous)
    assert verify(form(CURRENT)).digest == "abc123"
    with pytest.raises(TokenError):
        verify(form())
    for action in (links.CONFIRM, links.UNSUBSCRIBE):
        link = links.parse(CURRENT, action, mailed(CURRENT, action), now=1050)
        assert links.matches(CURRENT, link, "n" * 32)
        with pytest.raises(links.LinkInvalid):
            links.parse(CURRENT, action, mailed(OLD, action), now=1050)
    assert "private-retired-key" not in caplog.text


def test_previous_key_cannot_replace_a_missing_current_key(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", OLD)
    with pytest.raises(TokenError):
        verify_form("", form(), "acme.eu:1", "news", min_fill=0, max_age=60, now=1010)
    for action in (links.CONFIRM, links.UNSUBSCRIBE):
        with pytest.raises(links.LinkInvalid):
            links.parse("", action, mailed(OLD, action), now=1050)
