"""Fernet encryption for stored provider keys.

The key derives from ``SM_SECRET_KEY`` (SHA-256 → urlsafe base64), read
through a private BaseSettings from the environment or the root ``.env`` —
the same two sources the host's own BootstrapSettings uses, and no coupling
to app.state or hosting internals. The Fernet is cached for the process
lifetime (rotating the secret requires a restart, matching the session
middleware). Stored format is ``enc:v1:<fernet token>``:

- prefix present and decrypts        → plaintext key
- prefix present, decryption fails   → AiKeyUnreadableError (secret key changed)
- no prefix                          → treated as plaintext, warned once
  (covers keys pasted through the generic settings UI or seeded from env)
"""

from __future__ import annotations

import logging
from base64 import urlsafe_b64encode
from functools import lru_cache
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from pydantic_settings import BaseSettings, SettingsConfigDict

from sm_ai.contracts.errors import AiKeyUnreadableError

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"

# Fields already warned about this process — one line per field is signal,
# one per read is noise.
_warned_plaintext: set[str] = set()


class _CryptoEnv(BaseSettings):
    # ``env_file=".env"`` mirrors the host's BootstrapSettings: in the
    # documented dev flow the secret lives only in the root .env and is never
    # exported, so reading process env alone would 500 every key save.
    model_config = SettingsConfigDict(
        env_prefix="SM_", env_file=".env", extra="ignore"
    )

    secret_key: str = ""


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    secret = _CryptoEnv().secret_key
    if not secret:
        raise RuntimeError(
            "SM_SECRET_KEY is not set — the AI module needs it to encrypt "
            "stored provider keys."
        )
    return Fernet(urlsafe_b64encode(sha256(secret.encode()).digest()))


def encrypt_value(plain: str) -> str:
    """Encrypt a provider key for storage."""
    return ENC_PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt_value(stored: str, field: str) -> str:
    """Return the plaintext key for a stored value (see module docstring)."""
    if not stored:
        return ""
    if stored.startswith(ENC_PREFIX):
        try:
            return _fernet().decrypt(stored[len(ENC_PREFIX) :].encode()).decode()
        except InvalidToken as exc:
            raise AiKeyUnreadableError(field) from exc
    if field not in _warned_plaintext:
        _warned_plaintext.add(field)
        logger.warning(
            "AI setting %r is stored unencrypted; re-save it via the AI "
            "settings page to encrypt it.",
            field,
        )
    return stored
