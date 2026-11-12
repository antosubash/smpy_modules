"""Fernet encryption for the stored CAPTCHA secret (#350), with key rotation (#351).

A copy of ``sm_ai.core.crypto``, as billing's is: a published module must not
import a sibling optional module ("stored-secret crypto" parity family). The
secret is the running app's ``secret_key``, installed by
``RecordsModule.register_settings``; there is no ``SM_SECRET_KEY`` fallback.
The one thing read from the environment is ``SM_SECRET_KEY_PREVIOUS`` (the
process env, else the located ``.env``), and only for a value the current
secret does not open, so a malformed one never breaks what is current.

Stored formats:

- ``enc:v2:<fernet>`` — written by every supported path: the Settings screen
  and ``scripts/set_setting.py`` store the field's sealed dump
  (``public_submissions.captcha_secret``), and startup seals a legacy row. The
  Fernet key is HKDF-SHA256 of the secret with ``info`` ``sm_records:settings``.
- ``enc:v1:<fernet>`` — the 0.0.15 format of the other modules; read here for
  symmetry until 0.1.0.
- any other ``enc:`` prefix → CaptchaSecretUnreadableError, never plaintext.
- no prefix → a row stored before 0.0.16: treated as plaintext and warned once
  until startup seals it.
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

from sm_records.core.constants import PACKAGE

logger = logging.getLogger(__name__)


class CaptchaSecretUnreadableError(Exception):
    """The stored CAPTCHA secret no known key decrypts (``secret_key`` changed)."""

    def __init__(self, field: str) -> None:
        super().__init__(
            f"Records setting {field!r} cannot be decrypted with the app's secret_key or "
            "any key in SM_SECRET_KEY_PREVIOUS. If the secret was rotated, add the old "
            "key to SM_SECRET_KEY_PREVIOUS (see docs/secret-key-rotation.md), or "
            "re-enter it on the Settings screen."
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


# Records only: the provider an app installed, paired with "is that app still
# alive?" (``public_submissions.captcha_secret.install_secret_provider``).
_attached: tuple[Callable[[], str], Callable[[], bool]] | None = None


def attach_app(provider: Callable[[], str], alive: Callable[[], bool]) -> None:
    """Install ``provider`` as the secret source of the app ``alive`` watches."""
    global _attached
    set_secret_provider(provider)
    _attached = (provider, alive)


def has_secret_provider() -> bool:
    """Whether an app (or a script) is attached to supply the secret.

    Records only: ``SealedSecret`` dumps unsealed when nothing is attached — no
    provider, as in newsletter's worker, or the provider's app was garbage
    collected (a test suite builds many). An attached app whose ``secret_key``
    is empty still counts, so the dump raises there instead of writing the
    secret in the clear. A provider installed with plain ``set_secret_provider``
    (``scripts/reencrypt_secrets.py``) counts while it is the current one.
    """
    if _secret_provider is None:
        return False
    if _attached is not None and _attached[0] is _secret_provider:
        return _attached[1]()
    return True


def _current_secret() -> str:
    secret = _secret_provider() if _secret_provider is not None else ""
    if not secret:
        raise RuntimeError(
            "The app has no secret_key — the records module needs it to encrypt "
            "the stored CAPTCHA secret."
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
        )
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


def _unreadable(field: str) -> Exception:
    return CaptchaSecretUnreadableError(field)


def is_encrypted(value: str) -> bool:
    """Whether ``value`` carries an ``enc:`` prefix of any version."""
    return value.startswith("enc:")


def encrypt_value(plain: str) -> str:
    """Encrypt a value for storage, always in the current format."""
    return ENC_V2 + _keys((_current_secret(),), ENC_V2).encrypt(plain.encode()).decode()


def _open(token: str, version: str, field: str) -> str:
    current = _current_secret()
    try:
        return _keys((current,), version).decrypt(token.encode()).decode()
    except InvalidToken:
        pass
    # Only a value the current key cannot open reads SM_SECRET_KEY_PREVIOUS, so
    # a malformed variable (its RuntimeError) never breaks what is current.
    previous = tuple(s for s in dict.fromkeys(previous_secrets()) if s != current)
    if not previous:
        raise _unreadable(field)
    try:
        return _keys(previous, version).decrypt(token.encode()).decode()
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
                "Records setting %r is stored in the v1 format; run "
                "scripts/reencrypt_secrets.py or re-save it on the Settings screen.",
                field,
            )
        return plain
    if is_encrypted(stored):
        raise _unreadable(field)
    if field not in _warned_plaintext:
        _warned_plaintext.add(field)
        logger.warning(
            "Records setting %r is stored unencrypted; re-save it "
            "on the Settings screen to encrypt it.",
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
