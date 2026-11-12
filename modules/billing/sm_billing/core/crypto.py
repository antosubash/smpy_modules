"""Fernet encryption for the stored Stripe secrets, with key rotation (#351).

The pattern of ``sm_ai.core.crypto``, copied rather than imported: a published
module must not depend on a sibling optional module ("stored-secret crypto"
parity family). The secret is the running app's ``secret_key``, installed by
``BillingModule.register_settings``. Unlike the AI module there is no
``SM_SECRET_KEY`` fallback — the app's secret is always available once the
module is registered. The one thing read from the environment is
``SM_SECRET_KEY_PREVIOUS`` (the process env, else the located ``.env``).

Stored formats:

- ``enc:v2:<fernet>`` — written today, under HKDF-SHA256 of the secret with
  this module's own ``info`` (``sm_billing:settings``).
- ``enc:v1:<fernet>`` — the 0.0.15 format (SHA-256 of the secret). Still read,
  with one warning per field, until 0.1.0.
- any other ``enc:`` prefix → BillingKeyUnreadableError, never plaintext.
- no prefix → treated as plaintext, warned once per field (covers values set
  through the generic Settings screen or set_setting.py).

Both versions decrypt under the app's secret and every key in
``SM_SECRET_KEY_PREVIOUS`` (``docs/secret-key-rotation.md``).
"""

from __future__ import annotations

import json
import logging
import os
from base64 import urlsafe_b64encode
from collections.abc import Callable
from functools import lru_cache
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from sm_billing.core.constants import PACKAGE

logger = logging.getLogger(__name__)


class BillingKeyUnreadableError(Exception):
    """A stored secret no known key decrypts (``secret_key`` changed)."""

    def __init__(self, field: str) -> None:
        super().__init__(
            f"Billing setting {field!r} cannot be decrypted with the app's secret_key or "
            "any key in SM_SECRET_KEY_PREVIOUS. If the secret was rotated, add the old "
            "key to SM_SECRET_KEY_PREVIOUS (see docs/secret-key-rotation.md), or "
            "re-enter it on /admin/billing/connection."
        )
        self.field = field


ENC_V1 = "enc:v1:"
ENC_V2 = "enc:v2:"
PREVIOUS_ENV = "SM_SECRET_KEY_PREVIOUS"
_INFO = f"{PACKAGE}:settings".encode()

# Fields already warned about this process — one line per field is signal,
# one per read is noise.
_warned_plaintext: set[str] = set()
_warned_v1: set[str] = set()


# Installed at module registration: returns the running app's live secret.
_secret_provider: Callable[[], str] | None = None


def set_secret_provider(provider: Callable[[], str]) -> None:
    """Install the live-secret source."""
    global _secret_provider
    _secret_provider = provider


def _current_secret() -> str:
    secret = _secret_provider() if _secret_provider is not None else ""
    if not secret:
        raise RuntimeError(
            "The app has no secret_key — the billing module needs it to encrypt "
            "stored Stripe secrets."
        )
    return secret


def previous_secrets() -> tuple[str, ...]:
    """The retired secrets still accepted for decryption, newest first.

    ``SM_SECRET_KEY_PREVIOUS`` from the process environment, else from the
    project ``.env``: one bare key, or a JSON list of keys, each used exactly
    as given (the framework's ``.env`` parser trims a file value, as it does
    ``SM_SECRET_KEY``'s). A value that starts with ``[`` and is not a JSON
    list of strings is refused, naming the variable and never its value.
    """
    raw = os.environ.get(PREVIOUS_ENV)
    return _parse_previous(_dotenv_previous() if raw is None else raw)


@lru_cache(maxsize=1)
def _dotenv_previous() -> str:
    from simple_module_core.dotenv import find_env_file, parse_dotenv

    return parse_dotenv(find_env_file()).get(PREVIOUS_ENV, "")


@lru_cache(maxsize=8)
def _parse_previous(raw: str) -> tuple[str, ...]:
    # Keys are used exactly as given, like SM_SECRET_KEY itself: a secret may
    # start or end with whitespace, and a trimmed one derives another key.
    # Trimming only decides whether anything is configured at all.
    if not raw.strip():
        return ()
    if not raw.lstrip().startswith("["):
        return (raw,)
    try:
        values = json.loads(raw)
    except ValueError:
        values = None
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise RuntimeError(
            f"{PREVIOUS_ENV} must be one key or a JSON list of keys (its value is not shown)"
        ) from None
    return tuple(v for v in values if v.strip())


def _v1_key(secret: str) -> bytes:
    return urlsafe_b64encode(sha256(secret.encode()).digest())


def _v2_key(secret: str) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO)
    return urlsafe_b64encode(hkdf.derive(secret.encode()))


@lru_cache(maxsize=16)
def _keys(secrets: tuple[str, ...], version: str) -> MultiFernet:
    # Keyed by the secrets, not cached bare: the provider is consulted per
    # call, so a rotated secret applies to the very next call.
    derive = _v2_key if version == ENC_V2 else _v1_key
    return MultiFernet([Fernet(derive(secret)) for secret in secrets])


def _all_secrets() -> tuple[str, ...]:
    return tuple(dict.fromkeys(s for s in (_current_secret(), *previous_secrets()) if s))


def _unreadable(field: str) -> Exception:
    return BillingKeyUnreadableError(field)


def is_encrypted(value: str) -> bool:
    """Whether ``value`` carries an ``enc:`` prefix of any version."""
    return value.startswith("enc:")


def encrypt_value(plain: str) -> str:
    """Encrypt a value for storage, always in the current format."""
    return ENC_V2 + _keys((_current_secret(),), ENC_V2).encrypt(plain.encode()).decode()


def _open(token: str, version: str, field: str) -> str:
    try:
        return _keys(_all_secrets(), version).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise _unreadable(field) from exc


def decrypt_value(stored: str, field: str) -> str:
    """Return the plaintext for a stored value (see module docstring)."""
    if not stored:
        return ""
    if stored.startswith(ENC_V2):
        return _open(stored[len(ENC_V2) :], ENC_V2, field)
    if stored.startswith(ENC_V1):
        plain = _open(stored[len(ENC_V1) :], ENC_V1, field)
        if field not in _warned_v1:
            _warned_v1.add(field)
            logger.warning(
                "Billing setting %r is stored in the v1 format; run "
                "scripts/reencrypt_secrets.py or re-save it on /admin/billing/connection.",
                field,
            )
        return plain
    if is_encrypted(stored):
        raise _unreadable(field)
    if field not in _warned_plaintext:
        _warned_plaintext.add(field)
        logger.warning(
            "Billing setting %r is stored unencrypted; re-save it "
            "on /admin/billing/connection to encrypt it.",
            field,
        )
    return stored


def reencrypt_value(stored: str, field: str) -> str | None:
    """``stored`` re-encrypted under the current secret in the current format,
    or ``None`` when it is empty or already that. Plaintext is sealed too; a
    value no key opens raises the unreadable error."""
    if not stored:
        return None
    if stored.startswith(ENC_V2):
        try:
            _keys((_current_secret(),), ENC_V2).decrypt(stored[len(ENC_V2) :].encode())
        except InvalidToken:
            pass
        else:
            return None
    return encrypt_value(decrypt_value(stored, field))
