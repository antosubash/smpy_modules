"""Fernet encryption for the stored SMTP password.

The key derives from ``SM_SECRET_KEY`` (SHA-256 → urlsafe base64). The
running app's secret wins when the module is registered normally — hosts may
inject ``secret_key`` programmatically via ``create_app(settings=...)``, see
``set_secret_provider`` (a worker installs its own). The fallback is
``SM_SECRET_KEY`` from the process environment, then from the project ``.env``
*as the framework's own ``BootstrapSettings`` locates it* —
``$SM_PROJECT_ROOT/.env``, else a bounded walk up to the project root — never a
``.env`` resolved against whatever directory the process happens to run in
(#124). The provider and process env are re-consulted on every call (only the
``.env`` read is cached — it cannot change without a restart) and the derived
Fernet cached per secret, so an early call (before the app's live secret is
available) can never pin the fallback secret for the process.
Stored format is ``enc:v1:<fernet token>``:

- prefix present and decrypts        → plaintext key
- prefix present, decryption fails   → SmtpPasswordUnreadable (secret key changed)
- no prefix                          → treated as plaintext, warned once
  (an operator wrote the database directly)
"""

from __future__ import annotations

import logging
import os
from base64 import urlsafe_b64encode
from collections.abc import Callable
from functools import lru_cache
from hashlib import sha256
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

from sm_newsletter.core.errors import SmtpPasswordUnreadable

if TYPE_CHECKING:
    from simple_module_hosting.bootstrap_settings import BootstrapSettings

    from sm_newsletter.core.settings import NewsletterSettings

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"

# Fields already warned about this process — one line per field is signal,
# one per read is noise.
_warned_plaintext: set[str] = set()


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
            "SM_SECRET_KEY is not set — the newsletter module needs it to "
            "encrypt the SMTP password."
        )
    return _fernet_for(secret)


@lru_cache(maxsize=1)
def _dotenv_secret() -> str:
    """``SM_SECRET_KEY`` exactly as the host's own bootstrap read sees it.

    In the documented dev flow the secret lives only in the root ``.env`` and
    is never exported, so reading process env alone would 500 every key save.
    ``BootstrapSettings`` anchors that file through
    ``simple_module_core.dotenv.find_env_file`` — one convention for the web
    process, CLIs and workers. Its default is a placeholder, so only a value
    actually supplied counts.
    """
    from simple_module_hosting.bootstrap_settings import BootstrapSettings

    return explicit_secret(BootstrapSettings())


def explicit_secret(boot: BootstrapSettings) -> str:
    """The secret ``boot`` was actually given, or ``""`` for its placeholder default."""
    return boot.secret_key if "secret_key" in boot.model_fields_set else ""


@lru_cache(maxsize=4)
def _fernet_for(secret: str) -> Fernet:
    # Keyed by secret, not cached bare: the provider is consulted per call,
    # so the first caller racing module registration cannot freeze the
    # env/.env fallback in for the whole process.
    return Fernet(urlsafe_b64encode(sha256(secret.encode()).digest()))


def encrypt_value(plain: str) -> str:
    """Encrypt the SMTP password for storage."""
    return ENC_PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt_value(stored: str, field: str) -> str:
    """Return the plaintext for a stored value (see module docstring)."""
    if not stored:
        return ""
    if stored.startswith(ENC_PREFIX):
        try:
            return _fernet().decrypt(stored[len(ENC_PREFIX) :].encode()).decode()
        except InvalidToken as exc:
            raise SmtpPasswordUnreadable() from exc
    if field not in _warned_plaintext:
        _warned_plaintext.add(field)
        logger.warning(
            "Newsletter setting %r is stored unencrypted; re-save it through "
            "the password endpoint to encrypt it.",
            field,
        )
    return stored


def smtp_password(settings: NewsletterSettings) -> str:
    """The plaintext SMTP password held by ``settings``."""
    return decrypt_value(settings.smtp_password, "smtp_password")
