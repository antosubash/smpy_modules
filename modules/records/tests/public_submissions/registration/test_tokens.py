"""The registration token: bound to tenant, type, event and occurrence; a purpose of its own."""

from __future__ import annotations

import pytest
from sm_records.public_submissions import tokens
from sm_records.public_submissions.registration import tokens as reg

SECRET = "s3cret"
EVENT = "0b1d3f6e-5c1a-4f0e-9d3a-2b7c8e9f1a42"
KEY = f"{EVENT}:20260708T080000Z"
NOW = 1_800_000_000
KW = {"min_fill": 0, "max_age": 3600}


def sign(**over):
    args = {
        "secret": SECRET,
        "tenant": "default",
        "type_key": "regs",
        "digest": "abc123",
        "event_id": EVENT,
        "occurrence_key": KEY,
        "now": NOW,
        **over,
    }
    return reg.sign_registration(
        args.pop("secret"),
        args.pop("tenant"),
        args.pop("type_key"),
        args.pop("digest"),
        args.pop("event_id"),
        args.pop("occurrence_key"),
        **args,
    )


def verify(token, **over):
    args = {"tenant": "default", "type_key": "regs", **KW, "now": NOW + 10, **over}
    return reg.verify_registration(
        over.pop("secret", SECRET),
        token,
        args.pop("tenant"),
        args.pop("type_key"),
        **{k: v for k, v in args.items() if k in ("min_fill", "max_age", "now")},
    )


def test_round_trip():
    got = verify(sign())
    assert (got.digest, got.event_id, got.occurrence_key, got.issued) == (
        "abc123",
        EVENT,
        KEY,
        NOW,
    )
    assert len(sign().split(".")) == 6


def test_token_binds_event_and_occurrence():
    good = sign().split(".")
    for index, replacement in enumerate(
        ["other1", str(NOW + 1), "0" * 16, "11111111-1111-1111-1111-111111111111", KEY[:-1] + "1"]
    ):
        forged = list(good)
        forged[index] = replacement
        with pytest.raises(tokens.TokenError):
            verify(".".join(forged))
    with pytest.raises(tokens.TokenError):
        verify(sign(), tenant="other")
    with pytest.raises(tokens.TokenError):
        verify(sign(), type_key="other")
    with pytest.raises(tokens.TokenError):
        reg.verify_registration("another-secret", sign(), "default", "regs", **KW, now=NOW + 10)


def test_purpose_labels_differ():
    four = tokens.sign_form(SECRET, "default", "regs", "abc123", now=NOW)
    with pytest.raises(tokens.TokenError):
        verify(four)
    with pytest.raises(tokens.TokenError):
        tokens.verify_form(SECRET, sign(), "default", "regs", **KW, now=NOW + 10)
    # re-signed under the form label over the same parts
    digest, issued, nonce = "abc123", NOW, "00ff00ff00ff00ff"
    forged_mac = tokens._mac(SECRET, "form", "default", "regs", digest, issued, nonce, EVENT, KEY)
    with pytest.raises(tokens.TokenError):
        verify(f"{digest}.{issued}.{nonce}.{EVENT}.{KEY}.{forged_mac}")


@pytest.mark.parametrize(
    ("event_id", "key"),
    [
        (EVENT, KEY.replace(":", ".")),
        (EVENT, KEY + "|x"),
        (EVENT, KEY + " "),
        (EVENT, KEY.replace("08", "٠٨")),
        (EVENT.upper(), KEY),
        ("not-a-uuid", KEY),
        (EVENT, "11111111-1111-1111-1111-111111111111:20260708T080000Z"),  # another event's key
        (EVENT, f"{EVENT}:20261308T080000Z"),
        (EVENT, KEY + "\n"),
        (EVENT, ""),
    ],
)
def test_key_shapes_are_refused_before_the_mac(event_id, key):
    with pytest.raises(ValueError):
        sign(event_id=event_id, occurrence_key=key)


@pytest.mark.parametrize("junk", ["", "a.b.c", "x" * 400, "a.b.c.d.e.f.g", "é.1.2.3.4.5"])
def test_malformed_tokens(junk):
    with pytest.raises(tokens.TokenError):
        verify(junk)


def test_age_window():
    token = sign()
    with pytest.raises(tokens.TokenError):
        reg.verify_registration(
            SECRET, token, "default", "regs", min_fill=60, max_age=3600, now=NOW + 10
        )
    with pytest.raises(tokens.TokenError):
        reg.verify_registration(
            SECRET, token, "default", "regs", min_fill=0, max_age=5, now=NOW + 10
        )
