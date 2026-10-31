"""Settings for processes that never ran the web host's lifespan (#100).

A Celery worker imports consumer code and calls ``sm_ai.contracts`` without
``create_app`` ever registering the module, so the holder in
``sm_ai.services`` is empty. Instead of raising, ``current_settings()`` falls
back to :func:`load`, which hydrates ``AiSettings`` the way the web lifespan
does — the framework's own ``hydrate_settings`` over a ``SettingsStore``, so
the result is identical: the DB value, else the pydantic default
(``AiSettings`` reads no environment, #124).

Keys are decrypted by the unchanged ``resolve`` path, which needs the secret
the *web* app encrypts under. That is ``SM_SECRET_KEY`` from env or the
project ``.env`` (located by ``BootstrapSettings``, so ``SM_PROJECT_ROOT``
anchors it for a worker started elsewhere) when set explicitly, otherwise
the key the host generated and stored as ``host.secret_key``
(``simple_module_hosting._secret_key``) — so this installs a secret provider
resolving exactly that, read-only: a worker never generates a key.

Framework 0.0.35 has no cross-process settings signal — ``SettingsReloaded``
travels the web process's in-memory ``EventBus`` and never reaches a worker —
so the result is cached per process for ``LAZY_SETTINGS_TTL_SECONDS`` and a
save in the console applies to workers within that window. ``invalidate()``
forces the next call to re-read.

When the read fails (database down, unmigrated, no SQLite file yet) the
default fallback is kept only ``LAZY_SETTINGS_RETRY_SECONDS``, so a blip
does not pin a worker to the wrong provider for a minute. One thread
refreshes at a time; the others keep serving the previous snapshot meanwhile,
and the read itself is bounded by ``LAZY_SETTINGS_READ_TIMEOUT_SECONDS``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from sm_ai import constants, crypto
from sm_ai.settings import AiSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Snapshot:
    # Never in a repr: the settings hold the encrypted key, `secret` decrypts it.
    settings: AiSettings = field(repr=False)
    secret: str = field(repr=False)
    expires_at: float


_lock = threading.Lock()  # guards the module state below; never held across I/O
_refresh = threading.Lock()  # single-flight: one thread reads the database
_snapshot: _Snapshot | None = None
_last_secret = ""  # survives invalidate(), so a racing decrypt never sees ""
_warned = False


def _after_fork_in_child() -> None:
    # A prefork Celery parent may fork mid-refresh, leaving a lock held for
    # good in the child. Fresh locks and an empty cache; the child re-reads.
    global _lock, _refresh, _snapshot, _warned
    _lock, _refresh = threading.Lock(), threading.Lock()
    _snapshot, _warned = None, False


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


def load() -> AiSettings:
    """The process-cached hydrated settings, re-read once the TTL lapses."""
    return _current_snapshot().settings


def invalidate() -> None:
    """Drop the cache so the next call re-reads the database."""
    global _snapshot
    with _lock:
        _snapshot = None


def reset() -> None:
    """Forget everything, including the last secret and the warned flag (tests)."""
    global _last_secret, _warned
    invalidate()
    with _lock:
        _last_secret, _warned = "", False


def _current_snapshot() -> _Snapshot:
    global _snapshot, _last_secret
    with _lock:
        snap = _snapshot
    stale = snap is None or time.monotonic() >= snap.expires_at
    # With a stale snapshot in hand, don't queue behind another thread's read —
    # serve the stale one. With none at all, wait for it.
    if stale and _refresh.acquire(blocking=snap is None):
        try:
            with _lock:
                current = _snapshot
            if current is not None and time.monotonic() < current.expires_at:
                snap = current  # another thread refreshed while we waited
            else:
                settings, secret, from_db = _hydrate()
                ttl = (
                    constants.LAZY_SETTINGS_TTL_SECONDS
                    if from_db
                    else constants.LAZY_SETTINGS_RETRY_SECONDS
                )
                snap = _Snapshot(settings, secret, time.monotonic() + ttl)
                with _lock:
                    _snapshot = snap
                    _last_secret = secret or _last_secret
        finally:
            _refresh.release()
    # Never displace the web host's provider: registration installs one
    # bound to the live app, which is authoritative where it exists.
    if crypto._secret_provider is None:
        crypto.set_secret_provider(_worker_secret)
    assert snap is not None
    return snap


def _worker_secret() -> str:
    # "" lets crypto fall through to its own env/.env read and raise its
    # "SM_SECRET_KEY is not set" error.
    snap = _snapshot
    return (snap.secret if snap is not None else "") or _last_secret


def _hydrate() -> tuple[AiSettings, str, bool]:
    """Settings, the secret the web app encrypts keys under, and whether the
    database answered.

    The secret mirrors ``merge_host_settings``: ``SM_SECRET_KEY`` set
    explicitly in env or the project ``.env`` wins, else the stored one.

    A task may call ``resolve_model()`` from plain sync code or from inside
    ``asyncio.run(...)``; ``asyncio.run`` refuses to nest, so the read always
    runs on a private loop in a worker thread — the framework's own pre-app
    config read does the same.
    """
    global _warned
    from simple_module_hosting.bootstrap_settings import BootstrapSettings

    # Deliberately outside the try: a placeholder SM_SECRET_KEY in production
    # makes BootstrapSettings raise, and the web host refuses to boot on it too.
    boot = BootstrapSettings()
    explicit = crypto.explicit_secret(boot)
    reason = _unreadable(boot.database_url)
    if reason is None:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(lambda: asyncio.run(_bounded_read(boot.database_url)))
            settings, stored = future.result()
            _warned = False
            return settings, explicit or stored, True
        except Exception as exc:
            reason = type(exc).__name__
        finally:
            pool.shutdown(wait=False)
    # Only the reason is logged, never the message or traceback: a driver's
    # can carry the connection URL, credentials included. Once per outage.
    log = logger.debug if _warned else logger.warning
    _warned = True
    log("AI settings: database read failed (%s); using defaults", reason)
    return AiSettings(), explicit, False


def _unreadable(database_url: str) -> str | None:
    """Why the database should not be opened at all, or ``None``.

    A missing SQLite file would be *created*, empty, by connecting to it — a
    stray ``app.db`` wherever the worker runs — and then fail anyway.
    """
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        path = url.database or ""
        if path in ("", ":memory:") or not Path(path).is_file():
            return "no SQLite database file"
    return None


async def _bounded_read(database_url: str) -> tuple[AiSettings, str]:
    return await asyncio.wait_for(
        _read(database_url), timeout=constants.LAZY_SETTINGS_READ_TIMEOUT_SECONDS
    )


async def _read(database_url: str) -> tuple[AiSettings, str]:
    from settings.service import SettingService
    from settings.store import SettingsStore
    from simple_module_core.settings_hydrate import hydrate_settings
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
