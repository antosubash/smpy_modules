"""The secret key in a worker, where there is no app to ask (S11).

Order: ``SM_SECRET_KEY`` in the environment, then the ``.env`` the framework's
``BootstrapSettings`` locates (explicit values only), then the stored
``host.secret_key`` row. With none of them it refuses, so a worker never
decrypts under a guessed key or sends a link it cannot verify later.
"""

from __future__ import annotations

import os

from sm_newsletter.core import crypto

__all__ = ["SecretMissing", "install", "resolve_worker_secret"]


class SecretMissing(RuntimeError):  # noqa: N818 - reads as the condition it is
    """No secret key could be found for this worker."""


def _stored_secret() -> str:
    """The ``host.secret_key`` row; any failure to read it is "no row"."""
    try:
        from background_tasks.core import sync_db
        from simple_module_db.stored_settings import get_overrides_sync

        with sync_db.sync_session() as session:
            row = get_overrides_sync(session, "host").get("secret_key")
    except Exception:
        return ""
    return row[0] if row else ""


def resolve_worker_secret() -> str:
    secret = os.environ.get("SM_SECRET_KEY", "") or crypto._dotenv_secret() or _stored_secret()
    if not secret:
        raise SecretMissing(
            "no secret key: set SM_SECRET_KEY, or boot the app once so host.secret_key is stored"
        )
    return secret


def install(secret: str) -> None:
    """Make ``crypto`` use ``secret``, unless an app already installed a provider."""
    if crypto._secret_provider is None:
        crypto.set_secret_provider(lambda: secret)
