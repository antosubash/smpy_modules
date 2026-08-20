"""Fernet encryption for stored provider keys.

The key derives from ``SM_SECRET_KEY`` (SHA-256 → urlsafe base64). The
running app's secret wins when the module is registered normally — hosts may
inject ``secret_key`` programmatically via ``create_app(settings=...)``, see
``set_secret_provider`` — and a private BaseSettings reading the environment
or the root ``.env`` (the same two sources the host's own BootstrapSettings
uses) is the fallback. The provider and process env are re-consulted on
every call (only the ``.env`` file read is cached — it cannot change without
a restart) and the derived Fernet cached per secret, so an early call
(before the app's live secret is available) can never pin the fallback
secret for the process.
Stored format is ``enc:v1:<fernet token>``:

- prefix present and decrypts        → plaintext key
- prefix present, decryption fails   → AiKeyUnreadableError (secret key changed)
- no prefix                          → treated as plaintext, warned once
  (covers keys pasted through the generic settings UI or seeded from env)
"""

from __future__ import annotations

import logging
import os
from base64 import urlsafe_b64encode
from collections.abc import Callable
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


# Installed at module registration: returns the running app's live secret so
# encryption always matches the app; empty/None falls back to the env read.
_secret_provider: Callable[[], str] | None = None


def set_secret_provider(provider: Callable[[], str]) -> None:
    """Install the live-secret source."""
    global _secret_provider
    _secret_provider = provider


def _fernet() -> Fernet:
    secret = _secret_provider() if _secret_provider is not None else ""
    # Process env first (free), then the cached .env read: the file cannot
    # change without a restart, and an uncached BaseSettings would re-open
    # and re-parse it on every encrypt/decrypt inside async handlers.
    secret = secret or os.environ.get("SM_SECRET_KEY", "") or _dotenv_secret()
    if not secret:
        raise RuntimeError(
            "SM_SECRET_KEY is not set — the AI module needs it to encrypt "
            "stored provider keys."
        )
    return _fernet_for(secret)


@lru_cache(maxsize=1)
def _dotenv_secret() -> str:
    return _CryptoEnv().secret_key


@lru_cache(maxsize=4)
def _fernet_for(secret: str) -> Fernet:
    # Keyed by secret, not cached bare: the provider is consulted per call,
    # so the first caller racing module registration cannot freeze the
    # env/.env fallback in for the whole process.
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
