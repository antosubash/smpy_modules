"""Plugin discovery (plan decision 1).

A plugin is an ordinary framework module whose package ships
``images_extensions.py`` with ``def register(registry) -> None``. Workers
never build the app, so registration cannot hang off ``on_startup``: the web
process (images' ``on_startup``) and a worker (on first registry read) both
call :func:`load_extensions`, one code path, so both see the same registry.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
from collections.abc import Callable

from sm_images.pipeline import registry
from sm_images.pipeline.presets import Preset
from sm_images.pipeline.step import Step

__all__ = ["ENTRY_POINT_GROUP", "EXTENSIONS_MODULE", "Registrar", "load_extensions"]

ENTRY_POINT_GROUP = "simple_module"
EXTENSIONS_MODULE = "images_extensions"

_BUILTIN_LOADERS: list[Callable[[], None]] = []
"""Later tasks append a callable that ``register_builtin``s their steps."""


class Registrar:
    """What a plugin's ``register`` receives: registration only, no freeze or
    reset, and no reserved ids."""

    def register_step(self, step: Step) -> None:
        registry.register_step(step)

    def register_preset(self, preset: Preset) -> None:
        registry.register_preset(preset)


def _plugin_packages() -> list[str]:
    found = {
        ep.value.split(":")[0].split(".")[0]
        for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    }
    return sorted(found)


def load_extensions() -> None:
    """Register built-ins, then every installed plugin's, then freeze. A second
    call is a no-op. A failure empties the registry so a retry starts clean."""
    with registry._lock:
        if registry.is_frozen():
            return
        try:
            for loader in _BUILTIN_LOADERS:
                loader()
            registrar = Registrar()
            for pkg in _plugin_packages():
                try:
                    spec = importlib.util.find_spec(f"{pkg}.{EXTENSIONS_MODULE}")
                except ModuleNotFoundError:  # parent missing or not a package
                    continue
                if spec is None:
                    continue
                module = importlib.import_module(f"{pkg}.{EXTENSIONS_MODULE}")
                module.register(registrar)
            registry.freeze()
        except BaseException:
            registry.reset_registry()
            raise
