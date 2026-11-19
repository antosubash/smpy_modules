"""The reminder runtime in a Celery worker: a headless app, until the framework has a principal.

**The gap** (upstream simple_module_python #1005): a worker builds no app, so it has no user
directory, no membership store and no permission registry, and the framework offers no way to
ask "what does this user hold, outside a request". Reminders must not be sent to someone who
lost access, so a worker needs that answer.

**The stopgap.** The worker builds the host's app *without starting its lifespan*, with the
framework's own ``create_app(merge_host_settings())``, once per process and again after
:data:`TTL_SECONDS` (so a changed ``public_base_url`` is picked up). The app is only a bag of
the real pieces: the user directory, the membership store, the permission registry and its grant
sources, the host settings. On top of it the worker's principal is
:func:`~sm_events.core.access.offline.offline_accounts`, the very code the web process uses for
private feeds, and the database role overlay (what an admin edits on the permissions screen) is
replayed from the permissions module's own public service once per call, i.e. once per tick.
Measured on the demo host: about 16 s and 200 MB for the first build, then nothing; web and
worker images must be installed identically.

**What it may grant.** The principal built this way **never grants more than a request principal
for the same user** (the parity tests walk users x calendars x event states). It can grant less:
the membership role (``tenant:<role>``) a live request carries has no public read, so a user
whose only right comes from it is not reminded (#1005). That limit is reported to that user in
the request (:mod:`sm_events.reminders.access`), never silently.

**Fail closed.** No provisioned secret key (the worker would have to *create* the deployment's
session key to build the app; it refuses instead), a failed build, an unreadable overlay: each
answers ``None``, :func:`worker_runtime_supported` turns false for :data:`RETRY_SECONDS` (so
``availability`` says ``worker_access_unavailable`` and the tick sends nothing), the failure is
logged once by exception class, and the build is not retried inside that window (no crash loop).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sm_events.reminders import limits
from sm_events.reminders.runtime import ReminderRuntime, web_runtime

__all__ = [
    "RETRY_SECONDS",
    "TTL_SECONDS",
    "NoSecretKey",
    "reset_worker_app",
    "worker_runtime",
    "worker_runtime_supported",
]

logger = logging.getLogger(__name__)

TTL_SECONDS = limits.REMINDER_RUNTIME_TTL.total_seconds()
RETRY_SECONDS = 60.0
"""How long after a failure nothing is rebuilt (and reminders count as unavailable)."""

_lock = threading.Lock()


@dataclass
class _Built:
    app: Any
    at: float
    pid: int


_built: _Built | None = None
_failed_until: float = 0.0
_clock = time.monotonic


class NoSecretKey(RuntimeError):  # noqa: N818 - a refusal, named for what is missing
    """No signing key in the environment or the database: building the app would create it,
    and a worker must never provision a deployment's session key."""


def _has_key(bootstrap: Any) -> bool:
    from simple_module_hosting._preapp_config import load_host_overrides

    if "secret_key" in bootstrap.model_fields_set and bootstrap.secret_key:
        return True
    stored = load_host_overrides(bootstrap.database_url, strict=True)
    return bool(stored.get("secret_key", (None, None))[0])


def _merge(bootstrap: Any) -> Any:
    from simple_module_hosting import merge_host_settings

    return merge_host_settings(bootstrap)


def _settings() -> Any:
    """The host's settings, refusing when merging them would have to create a key."""
    from simple_module_hosting.bootstrap_settings import BootstrapSettings

    bootstrap = BootstrapSettings()
    if not _has_key(bootstrap):
        raise NoSecretKey
    return _merge(bootstrap)


def _create_app(settings: Any) -> Any:
    from simple_module_hosting import create_app

    return create_app(settings)


def _db_factory() -> Any:
    from sm_events.core.worker import worker_session_factory

    return worker_session_factory()


async def _replay_overlay_default(app: Any, db: Any) -> None:
    """The permissions module's own replay of the role overlay into the live registry."""
    from permissions.core.service import PermissionService

    registry = app.state.sm.permissions
    await PermissionService(db, registry).load_all_into_registry()


_replay_overlay: Any = _replay_overlay_default
"""Replaced by ``None`` in a test of a host without the permissions module."""


def _permissions_installed() -> bool:
    try:
        import permissions.core.service  # noqa: F401
    except ImportError:
        return False
    return True


def _build() -> Any:
    with _lock:
        app = _create_app(_settings())
        sm = app.state.sm
        if getattr(sm, "db", None) is None:
            sm.db = SimpleNamespace(session_factory=_db_factory())
        return app


def _fail(exc: BaseException) -> None:
    global _failed_until
    _failed_until = _clock() + RETRY_SECONDS
    logger.warning("events: the reminder worker runtime is unavailable (%s)", type(exc).__name__)


def worker_runtime_supported() -> bool:
    """False for a short while after a failed build or overlay read. A worker's failure is seen
    by this process only; the web process cannot see it and reports its own state."""
    return _clock() >= _failed_until


def reset_worker_app() -> None:
    """Forget the app and any failure (``worker_process_init``, tests)."""
    global _built, _failed_until
    _built, _failed_until = None, 0.0


async def worker_runtime(db: Any) -> ReminderRuntime | None:
    """The runtime for one tick, or ``None`` (fail closed)."""
    global _built
    now = _clock()
    if now < _failed_until:
        return None
    built = _built
    if built is None or built.pid != os.getpid() or now - built.at >= TTL_SECONDS:
        try:
            app = await asyncio.to_thread(_build)
        except Exception as exc:  # the class only: a message can quote settings
            _fail(exc)
            return None
        built = _built = _Built(app, now, os.getpid())
    if _replay_overlay is not None and _permissions_installed():
        try:
            await _replay_overlay(built.app, db)
        except Exception as exc:
            _fail(exc)
            return None
    return web_runtime(built.app)
