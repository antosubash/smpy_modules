"""Module-scoped state container plus the module-global holder.

``AiServices`` is stored as ``app.state.sm_ai`` by
:meth:`AiModule.register_settings` (via ``register_module_settings``); the
hosting lifespan hydrates ``settings`` from the DB before ``on_startup`` and
``settings.reload.apply_changes_and_reload`` hot-swaps it on save — both by
assigning ``services.settings`` on the *same instance*.

``install`` keeps a module-global reference to that instance so
``sm_ai.contracts`` works by direct import: consumers never touch app.state
and pass no sessions.
"""

from __future__ import annotations

from dataclasses import dataclass

from sm_ai.contracts.errors import AiNotConfiguredError
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
    """Drop the installed instance (tests only)."""
    global _current
    _current = None


def current_settings() -> AiSettings:
    """The hydrated settings of the running host."""
    if _current is None:
        raise AiNotConfiguredError(
            "module",
            "The AI module is not initialised — is a host running with "
            "simple_module_ai installed?",
        )
    return _current.settings
