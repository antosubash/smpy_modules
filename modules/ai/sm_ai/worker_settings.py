"""Settings for processes that never ran the web host's lifespan (#100).

A Celery worker imports consumer code and calls ``sm_ai.contracts`` without
``create_app`` ever registering the module, so the holder in
``sm_ai.services`` is empty. Instead of raising, ``current_settings()`` falls
back to :func:`load`, which hydrates ``AiSettings`` the way the web lifespan
does — the framework's own ``hydrate_settings`` over a ``SettingsStore``, so
the precedence is identical: DB override, then ``SM_AI_*`` env / ``.env``,
then the pydantic default.

Keys are decrypted by the unchanged ``resolve`` path, which needs the secret
the *web* app encrypts under. That is ``SM_SECRET_KEY`` from env / ``.env``
when set explicitly, otherwise the key the host generated and stored as
``host.secret_key`` (``simple_module_hosting._secret_key``) — so this installs
a secret provider resolving exactly that, read-only: a worker never generates
a key.

Framework 0.0.35 has no cross-process settings signal — ``SettingsReloaded``
travels the web process's in-memory ``EventBus`` and never reaches a worker —
so the result is cached per process for ``LAZY_SETTINGS_TTL_SECONDS`` and a
save in the console applies to workers within that window. ``invalidate()``
forces the next call to re-read.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sm_ai import constants, crypto
from sm_ai.settings import AiSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Snapshot:
    settings: AiSettings
    secret: str
    expires_at: float


_lock = threading.Lock()
_snapshot: _Snapshot | None = None


def load() -> AiSettings:
    """The process-cached hydrated settings, re-read once the TTL lapses."""
    return _current_snapshot().settings


def invalidate() -> None:
    """Drop the cache so the next call re-reads the database."""
    global _snapshot
    with _lock:
        _snapshot = None


def _current_snapshot() -> _Snapshot:
    global _snapshot
    with _lock:
        snap = _snapshot
        if snap is None or time.monotonic() >= snap.expires_at:
            settings, secret = _hydrate()
            snap = _Snapshot(
                settings, secret, time.monotonic() + constants.LAZY_SETTINGS_TTL_SECONDS
            )
            _snapshot = snap
        # Never displace the web host's provider: registration installs one
        # bound to the live app, which is authoritative where it exists.
        if crypto._secret_provider is None:
            crypto.set_secret_provider(_worker_secret)
        return snap


def _worker_secret() -> str:
    # "" lets crypto fall through to its own env/.env read and raise its
    # "SM_SECRET_KEY is not set" error.
    snap = _snapshot
    return snap.secret if snap is not None else ""


def _hydrate() -> tuple[AiSettings, str]:
    """Settings plus the secret the web app encrypts keys under.

    The secret mirrors ``merge_host_settings``: ``SM_SECRET_KEY`` set
    explicitly in env or the project ``.env`` wins, else the stored one.

    The async read runs on a private loop, whatever loop the caller is on.

    A task may call ``resolve_model()`` from plain sync code or from inside
    ``asyncio.run(...)``; ``asyncio.run`` refuses to nest, so the read always
    runs in a worker thread — the framework's own pre-app config read does
    the same.
    """
    from simple_module_hosting.bootstrap_settings import BootstrapSettings

    boot = BootstrapSettings()
    explicit = boot.secret_key if "secret_key" in boot.model_fields_set else ""
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            settings, stored = pool.submit(lambda: asyncio.run(_read(boot.database_url))).result()
        return settings, explicit or stored
    except Exception as exc:
        # Unreachable or unmigrated database: the web lifespan's hydrate step
        # falls back the same way. Env and defaults still apply. Only the error
        # type is logged: a driver's message or traceback can carry the
        # connection URL, credentials included.
        logger.warning(
            "AI settings: database read failed (%s); using SM_AI_* env and defaults",
            type(exc).__name__,
        )
        return AiSettings(), explicit


async def _read(database_url: str) -> tuple[AiSettings, str]:
    from settings.hydrate import hydrate_settings
    from settings.service import SettingService
    from settings.store import SettingsStore
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with AsyncSession(engine) as session:
            store = SettingsStore(SettingService(session))
            settings = await hydrate_settings(AiSettings, store, constants.PACKAGE)
            host = await store.get_overrides(constants.HOST_SETTINGS_PACKAGE)
    finally:
        await engine.dispose()
    secret = host.get(constants.HOST_SECRET_FIELD, ("", ""))[0]
    return settings, secret
