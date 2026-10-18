"""Module-scoped state container plus the module-global holder.

``AiServices`` is stored as ``app.state.sm_ai`` by
:meth:`AiModule.register_settings` (via ``register_module_settings``); the
hosting lifespan hydrates ``settings`` from the DB before ``on_startup`` and
``settings.reload.apply_changes_and_reload`` hot-swaps it on save — both by
assigning ``services.settings`` on the *same instance*.

``install`` keeps a module-global reference to that instance so
``sm_ai.contracts`` works by direct import: consumers never touch app.state
and pass no sessions.

A process that never registered the module — a Celery worker, a script —
has no holder; ``current_settings`` then hydrates lazily through
``sm_ai.worker_settings`` (#100) instead of failing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sm_ai import worker_settings
from sm_ai.settings import AiSettings


@dataclass
class AiServices:
    """AI module singletons."""

    settings: AiSettings


_current: AiServices | None = None


def install(services: AiServices) -> AiServices:
    """Record the host's AiServices instance; returns it for the factory."""
    global _current
    _current = services
    return services


def reset() -> None:
    """Drop the installed instance and the lazy cache (tests only)."""
    global _current
    _current = None
    worker_settings.invalidate()


def invalidate() -> None:
    """Re-read settings on the next call where no holder is installed.

    A no-op for the web host, whose holder is hot-swapped on save.
    """
    worker_settings.invalidate()


def current_settings() -> AiSettings:
    """The hydrated settings of the running host — or, with no host, of the DB."""
    if _current is None:
        return worker_settings.load()
    return _current.settings
