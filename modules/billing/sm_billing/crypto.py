"""Fernet encryption for the stored Stripe secrets.

The pattern of ``sm_ai.crypto``, copied rather than imported: a published
module must not depend on a sibling optional module. The key derives from the
running app's ``secret_key`` (SHA-256 → urlsafe base64), installed by
``BillingModule.register_settings``. Unlike the AI module there is no
environment fallback — billing reads no environment, and the app's secret is
always available once the module is registered.

Stored format is ``enc:v1:<fernet token>``:

- prefix present and decrypts        → plaintext secret
- prefix present, decryption fails   → BillingKeyUnreadableError (secret_key changed)
- no prefix                          → treated as plaintext, warned once per field
  (covers values set through the generic Settings screen or set_setting.py)
"""

from __future__ import annotations

import logging
from base64 import urlsafe_b64encode
from collections.abc import Callable
from functools import lru_cache
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"

_warned_plaintext: set[str] = set()
_secret_provider: Callable[[], str] | None = None


class BillingKeyUnreadableError(Exception):
    """A stored secret was encrypted under a different ``secret_key``."""

    def __init__(self, field: str) -> None:
        super().__init__(
            f"Billing setting {field!r} cannot be decrypted — the app's secret_key "
            "changed since it was saved. Re-enter it on /admin/billing/connection."
        )
        self.field = field


def set_secret_provider(provider: Callable[[], str]) -> None:
    """Install the live-secret source (the running app's ``secret_key``)."""
    global _secret_provider
    _secret_provider = provider


def _fernet() -> Fernet:
    secret = _secret_provider() if _secret_provider is not None else ""
    if not secret:
        raise RuntimeError(
            "The app has no secret_key — the billing module needs it to encrypt "
            "stored Stripe secrets."
        )
    return _fernet_for(secret)


@lru_cache(maxsize=4)
def _fernet_for(secret: str) -> Fernet:
    return Fernet(urlsafe_b64encode(sha256(secret.encode()).digest()))


def encrypt_value(plain: str) -> str:
    """Encrypt a secret for storage."""
    return ENC_PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt_value(stored: str, field: str) -> str:
    """Return the plaintext for a stored value (see module docstring)."""
    if not stored:
        return ""
    if stored.startswith(ENC_PREFIX):
        try:
            return _fernet().decrypt(stored[len(ENC_PREFIX) :].encode()).decode()
        except InvalidToken as exc:
            raise BillingKeyUnreadableError(field) from exc
    if field not in _warned_plaintext:
        _warned_plaintext.add(field)
        logger.warning(
            "Billing setting %r is stored unencrypted; re-save it on "
            "/admin/billing/connection to encrypt it.",
            field,
        )
    return stored
