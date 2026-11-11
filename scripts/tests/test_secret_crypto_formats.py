"""The stored-secret formats, pinned by value across the four copies (#351, #350).

``parity_crypto.py`` pins that the copies are one design; this pins the bytes:
a known secret derives a known ``enc:v2:`` key per module (RFC 5869 HKDF-SHA256,
no salt, ``info = <package>:settings``), the four keys differ from each other
and from the 0.0.15 ``enc:v1:`` key, and each copy still opens a ``v1`` token
made the 0.0.15 way. A change here strands every stored secret.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

import pytest
from cryptography.fernet import Fernet
from sm_ai.core import crypto as ai_crypto
from sm_billing.core import crypto as billing_crypto
from sm_newsletter.core import crypto as newsletter_crypto
from sm_records.core import crypto as records_crypto

SECRET = "known-answer-secret"

# Computed independently (hmac + hashlib, RFC 5869) when the format was set.
V2_KEYS = {
    ai_crypto: "W2Yh0coaqyeRO3XsFj33EYUfd_hXaKo1ciNOckuk8LQ=",
    billing_crypto: "jyW-hNbxkQSmj-bydTrm4H16M1RJp3qx3C7DIKNIyBs=",
    newsletter_crypto: "AsZ9KyOIPI705H9TmiCwXEv4K1TZOJjmjSrbx0tV7r0=",
    records_crypto: "GoG28-KcF8RMX3djVR8r8wd97TD1MyWw4KFrqLOEoFg=",
}
V1_KEY = "Sj9vsKUhF1xNVvEk7w0eDWmR2wqDLx5Z7kw0EvtfwbY="
MODULES = list(V2_KEYS)
IDS = [m.__name__.split(".")[0] for m in MODULES]


@pytest.fixture(autouse=True)
def _known_secret(monkeypatch):
    monkeypatch.delenv("SM_SECRET_KEY_PREVIOUS", raising=False)
    for module in MODULES:
        monkeypatch.setattr(module, "_secret_provider", lambda: SECRET)
        module._dotenv_previous.cache_clear()
    yield
    for module in MODULES:
        module._dotenv_previous.cache_clear()


@pytest.mark.parametrize("module", MODULES, ids=IDS)
def test_v2_key_is_the_known_answer(module):
    assert module._v2_key(SECRET).decode() == V2_KEYS[module]
    assert module._v1_key(SECRET).decode() == V1_KEY


def test_every_module_has_its_own_key():
    keys = set(V2_KEYS.values()) | {V1_KEY}
    assert len(keys) == len(MODULES) + 1


@pytest.mark.parametrize("module", MODULES, ids=IDS)
def test_a_v1_token_made_the_0_0_15_way_still_opens(module):
    legacy = Fernet(urlsafe_b64encode(sha256(SECRET.encode()).digest()))
    stored = "enc:v1:" + legacy.encrypt(b"pw").decode()
    assert module.decrypt_value(stored, "field") == "pw"


@pytest.mark.parametrize("module", MODULES, ids=IDS)
def test_writes_are_v2_under_the_known_key(module):
    stored = module.encrypt_value("pw")
    assert stored.startswith("enc:v2:")
    assert Fernet(V2_KEYS[module].encode()).decrypt(stored[7:].encode()) == b"pw"


def test_one_modules_token_does_not_open_in_another():
    stored = ai_crypto.encrypt_value("pw")
    with pytest.raises(billing_crypto.BillingKeyUnreadableError):
        billing_crypto.decrypt_value(stored, "stripe_secret_key")
