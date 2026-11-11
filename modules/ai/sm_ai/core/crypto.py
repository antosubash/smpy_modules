"""Fernet encryption for stored provider keys, with key rotation (#351).

The secret is ``SM_SECRET_KEY``. The running app's secret wins when the module
is registered normally — hosts may inject ``secret_key`` programmatically via
``create_app(settings=...)``, see ``set_secret_provider`` (a Celery worker
installs its own, see ``sm_ai.core.worker_settings``). The fallback is
``SM_SECRET_KEY`` from the process environment, then from the project ``.env``
*as the framework's own ``BootstrapSettings`` locates it* — never a ``.env``
resolved against whatever directory the process happens to run in (#124). The
provider and process env are re-consulted on every call (only the ``.env``
reads are cached — the file cannot change without a restart).

Stored formats:

- ``enc:v2:<fernet>`` — written today. The Fernet key is HKDF-SHA256 of the
  secret with this module's own ``info`` (``sm_ai:settings``), so no two
  modules share a key.
- ``enc:v1:<fernet>`` — the 0.0.15 format (SHA-256 of the secret). Still read,
  with one warning per field, until 0.1.0; ``scripts/reencrypt_secrets.py`` or
  a re-save upgrades it.
- any other ``enc:`` prefix → AiKeyUnreadableError, never plaintext.
- no prefix → treated as plaintext, warned once per field.

Both versions decrypt under ``SM_SECRET_KEY`` and every key in
``SM_SECRET_KEY_PREVIOUS`` (process env, else the located ``.env``): one bare
key, or a JSON list of keys. That is what lets an operator rotate the secret
without losing what is stored (``docs/secret-key-rotation.md``). A value no
key opens raises AiKeyUnreadableError.
"""

from __future__ import annotations

import json
import logging
import os
from base64 import urlsafe_b64encode
from collections.abc import Callable
from functools import lru_cache
from hashlib import sha256
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from sm_ai.contracts.errors import AiKeyUnreadableError
from sm_ai.core.constants import PACKAGE

if TYPE_CHECKING:
    from simple_module_hosting.bootstrap_settings import BootstrapSettings

logger = logging.getLogger(__name__)

ENC_V1 = "enc:v1:"
ENC_V2 = "enc:v2:"
PREVIOUS_ENV = "SM_SECRET_KEY_PREVIOUS"
_INFO = f"{PACKAGE}:settings".encode()

# Fields already warned about this process — one line per field is signal,
# one per read is noise.
_warned_plaintext: set[str] = set()
_warned_v1: set[str] = set()


# Installed at module registration: returns the running app's live secret so
# encryption always matches the app; empty/None falls back to the env read.
_secret_provider: Callable[[], str] | None = None


def set_secret_provider(provider: Callable[[], str]) -> None:
    """Install the live-secret source."""
    global _secret_provider
    _secret_provider = provider


def _current_secret() -> str:
    secret = _secret_provider() if _secret_provider is not None else ""
    # Process env first (free), then the cached .env read: the file cannot
    # change without a restart, and an uncached BaseSettings would re-open
    # and re-parse it on every encrypt/decrypt inside async handlers.
    secret = secret or os.environ.get("SM_SECRET_KEY", "") or _dotenv_secret()
    if not secret:
        raise RuntimeError(
            "SM_SECRET_KEY is not set — the AI module needs it to encrypt stored provider keys."
        )
    return secret


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


def previous_secrets() -> tuple[str, ...]:
    """The retired secrets still accepted for decryption, newest first.

    ``SM_SECRET_KEY_PREVIOUS`` from the process environment, else from the
    project ``.env``: one bare key, or a JSON list of keys. A value that starts
    with ``[`` and is not a JSON list of strings is refused, naming the
    variable and never its value.
    """
    raw = os.environ.get(PREVIOUS_ENV)
    return _parse_previous(_dotenv_previous() if raw is None else raw)


@lru_cache(maxsize=1)
def _dotenv_previous() -> str:
    from simple_module_core.dotenv import find_env_file, parse_dotenv

    return parse_dotenv(find_env_file()).get(PREVIOUS_ENV, "")


@lru_cache(maxsize=8)
def _parse_previous(raw: str) -> tuple[str, ...]:
    text = raw.strip()
    if not text:
        return ()
    if not text.startswith("["):
        return (text,)
    try:
        values = json.loads(text)
    except ValueError:
        values = None
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise RuntimeError(
            f"{PREVIOUS_ENV} must be one key or a JSON list of keys (its value is not shown)"
        ) from None
    return tuple(v.strip() for v in values if v.strip())


def _v1_key(secret: str) -> bytes:
    return urlsafe_b64encode(sha256(secret.encode()).digest())


def _v2_key(secret: str) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO)
    return urlsafe_b64encode(hkdf.derive(secret.encode()))


@lru_cache(maxsize=16)
def _keys(secrets: tuple[str, ...], version: str) -> MultiFernet:
    # Keyed by the secrets, not cached bare: the provider is consulted per
    # call, so the first caller racing module registration cannot freeze the
    # env/.env fallback in for the whole process.
    derive = _v2_key if version == ENC_V2 else _v1_key
    return MultiFernet([Fernet(derive(secret)) for secret in secrets])


def _all_secrets() -> tuple[str, ...]:
    return tuple(dict.fromkeys(s for s in (_current_secret(), *previous_secrets()) if s))


def _unreadable(field: str) -> Exception:
    return AiKeyUnreadableError(field)


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
                "AI setting %r is stored in the v1 format; run "
                "scripts/reencrypt_secrets.py or re-save it via the AI settings page.",
                field,
            )
        return plain
    if is_encrypted(stored):
        raise _unreadable(field)
    if field not in _warned_plaintext:
        _warned_plaintext.add(field)
        logger.warning(
            "AI setting %r is stored unencrypted; re-save it via the AI "
            "settings page to encrypt it.",
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
