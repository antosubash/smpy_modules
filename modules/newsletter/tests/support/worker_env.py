"""A worker's environment for the secret and dispatch tests (S11).

No ``SM_SECRET_KEY`` in the environment, no ``.env`` the framework's
``BootstrapSettings`` could find (``SM_PROJECT_ROOT`` points at an empty
folder), no app secret provider, and no cached ``.env`` read or worker
settings left over from another test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from background_tasks.worker.settings import clear_settings_cache
from sm_newsletter.core import crypto


def isolate_worker_env(monkeypatch: Any, root: Path) -> None:
    """Strip every secret source but a stored row; undone by ``monkeypatch``
    plus :func:`reset_worker_caches` at teardown."""
    monkeypatch.setenv("SM_PROJECT_ROOT", str(root))
    monkeypatch.delenv("SM_SECRET_KEY", raising=False)
    monkeypatch.setattr(crypto, "_secret_provider", None)
    reset_worker_caches()


def reset_worker_caches() -> None:
    crypto._dotenv_secret.cache_clear()
    clear_settings_cache()


def encrypted(plain: str, under: str) -> str:
    """``plain`` as a stored secret encrypted under the key ``under``."""
    return crypto.ENC_PREFIX + crypto._fernet_for(under).encrypt(plain.encode()).decode()
