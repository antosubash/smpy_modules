"""A feed token: its shape, its entropy and the one thing that is stored of it."""

from __future__ import annotations

import base64
import hashlib

import pytest
from sm_events.feeds.tokens.codec import hash_token, new_token, well_formed


def test_shape_and_entropy():
    tokens = {new_token() for _ in range(1000)}
    assert len(tokens) == 1000
    for token in tokens:
        assert well_formed(token)
        assert token.startswith("evf_")
        assert len(token) == 47
        assert len(base64.urlsafe_b64decode(token[4:] + "=")) == 32


def test_hash_is_sha256_hex():
    assert hash_token("evf_x") == hashlib.sha256(b"evf_x").hexdigest()
    assert len(hash_token(new_token())) == 64


def test_hash_is_not_the_token():
    token = new_token()
    assert token not in hash_token(token)
    assert token[4:] not in hash_token(token)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "evf_",
        "x" * 47,
        "evf_" + "a" * 42,
        "evf_" + "a" * 44,
        "evf_" + "a" * 20 + "+" + "a" * 22,
        "evf_" + "a" * 20 + "/" + "a" * 22,
        "evf_" + "a" * 43 + "\n",
        "\nevf_" + "a" * 43,
        "EVF_" + "a" * 43,
        "evf_" + "é" * 43,
        "evf_" + "a" * 10_000,
        "a" * 10_000,
    ],
)
def test_well_formed_refuses(bad):
    assert not well_formed(bad)


def test_well_formed_accepts_the_alphabet():
    assert well_formed("evf_" + "Aa0_-" * 8 + "Aa0")
