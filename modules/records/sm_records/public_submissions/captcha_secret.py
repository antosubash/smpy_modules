"""The CAPTCHA secret at rest (#350): encrypted, decrypted only to verify.

``public_submissions_captcha_secret`` is a
:data:`~sm_records.core.settings.settings_public_submissions.SealedSecret`, so
every supported write already stores ``enc:v2:…``: the Settings screen and
``scripts/set_setting.py`` both store the field's sealed dump, and the generic
row API refuses module keys. What is left for this module:

* :func:`install_secret_provider` — from ``register_settings``, so the key is
  there before anything hydrates or dumps the settings, including the headless
  scripts that build the app without starting it.
* :func:`seal_stored` — at startup, encrypts a row stored before 0.0.16 (or
  written around the supported paths). It is a compare-and-set on
  ``(scope, scope_id, key)`` and the plaintext it read, so a concurrent save is
  never overwritten; until it runs, the plaintext row still verifies.
* :func:`secret` — the plaintext for :func:`~.captcha.verify`, never cached.

SYSTEM scope only: the records settings class is one deployment's settings.
"""

from __future__ import annotations

import json
import logging
import weakref
from typing import Any

from fastapi import FastAPI
from sqlalchemy import and_, select, update

from sm_records.core import constants, crypto
from sm_records.core.settings import RecordsSettings
from sm_records.core.settings.settings_public_submissions import seal_secret

__all__ = [
    "FIELD",
    "KEY",
    "install_secret_provider",
    "seal_at_startup",
    "seal_stored",
    "secret",
]

logger = logging.getLogger(__name__)

FIELD = "public_submissions_captcha_secret"
KEY = f"{constants.PACKAGE}.{FIELD}"
"""The ``settings_setting`` key the framework stores the field under."""


def install_secret_provider(app: FastAPI) -> None:
    """Make :mod:`sm_records.core.crypto` encrypt under this app's secret key.

    Lazily and through a weakref, as ai and billing do: ``app.state.sm`` is
    assigned after ``register_settings``, and the provider is process-global,
    so a strong closure would keep a discarded test app alive.
    """
    app_ref = weakref.ref(app)

    def _live_secret() -> str:
        live_app = app_ref()
        if live_app is None:
            return ""
        sm = getattr(live_app.state, "sm", None)
        return getattr(getattr(sm, "settings", None), "secret_key", "") or ""

    # Paired with the weakref, so "the app is gone" (dump as held) is never
    # confused with "the app has no key" (refuse to dump in the clear).
    crypto.attach_app(_live_secret, lambda: app_ref() is not None)


def secret(settings: RecordsSettings) -> str:
    """The plaintext CAPTCHA secret (``""`` when none is set).

    Raises :class:`~sm_records.core.crypto.CaptchaSecretUnreadableError` when no
    known key opens it, and ``RuntimeError`` when the app has no secret key.
    """
    return crypto.decrypt_value(settings.public_submissions_captcha_secret or "", FIELD).strip()


def _plaintext(value: str, value_type: str) -> str | None:
    """The stored plaintext, or ``None`` when the row is empty or encrypted."""
    if value_type == "json":
        try:
            value = json.loads(value)
        except ValueError:
            return None  # not a value hydration could read either
        if not isinstance(value, str):
            return None
    text = value.strip()
    return text if text and not crypto.is_encrypted(text) else None


async def seal_stored(session_factory: Any) -> str | None:
    """Encrypt a plaintext stored CAPTCHA secret in place.

    Returns the sealed value written, or ``None`` when there was nothing to do
    (no row, empty, already encrypted, or another process changed it first).
    The value is never logged.
    """
    from simple_module_db.stored_settings import (
        SCOPE_SYSTEM,
        SYSTEM_SCOPE_ID,
        settings_table_clause,
        settings_table_exists,
    )
    from simple_module_db.transaction import finalize_session

    table = settings_table_clause()
    where = and_(
        table.c.scope == SCOPE_SYSTEM,
        table.c.scope_id == SYSTEM_SCOPE_ID,
        table.c.key == KEY,
    )
    async with session_factory() as session:
        if not await settings_table_exists(session):  # a fresh install, before migrations
            return None
        row = (
            await session.execute(select(table.c.value, table.c.value_type).where(where))
        ).first()
        plain = _plaintext(row[0], row[1]) if row is not None else None
        if plain is None:
            await finalize_session(session)
            return None
        sealed = seal_secret(plain)
        stored = json.dumps(sealed) if row[1] == "json" else sealed
        result = await session.execute(
            update(table).where(where, table.c.value == row[0]).values(value=stored)
        )
        await finalize_session(session)
    if result.rowcount != 1:
        logger.info("records: the CAPTCHA secret changed while it was being sealed; left as is")
        return None
    logger.warning("records: the stored CAPTCHA secret was unencrypted; it is now stored encrypted")
    return sealed


async def seal_at_startup(app: FastAPI, module: Any) -> None:
    """:func:`seal_stored`, then the live settings, at ``on_startup``.

    A failure costs a log line, never the boot: the plaintext row keeps
    verifying, and the next startup tries again.
    """
    db = getattr(module, "db", None)
    services = getattr(app.state, constants.PACKAGE, None)
    if db is None or services is None:
        return
    try:
        sealed = await seal_stored(db.session_factory)
    except Exception as exc:
        logger.error("records: could not seal the stored CAPTCHA secret (%s)", type(exc).__name__)
        return
    held = getattr(services, "settings", None)
    if sealed is None or held is None:
        return
    # Every holder of the hydrated object: the services container (what every
    # request and newsletter read, per call) and the module instance, which
    # ``boot.startup`` assigns from the container right after this — swapped
    # here too, so the order of the two cannot leave it on the plaintext.
    services.settings = held.model_copy(update={FIELD: sealed})
    if getattr(module, "settings", None) is held:
        module.settings = services.settings
