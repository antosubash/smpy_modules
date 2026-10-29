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
import logging
from collections.abc import Callable

from sm_images.pipeline import registry
from sm_images.pipeline.presets import Preset
from sm_images.pipeline.step import Step

__all__ = ["ENTRY_POINT_GROUP", "EXTENSIONS_MODULE", "Registrar", "load_extensions"]

ENTRY_POINT_GROUP = "simple_module"
EXTENSIONS_MODULE = "images_extensions"

logger = logging.getLogger(__name__)


def _load_builtin_steps() -> None:
    from sm_images.pipeline.builtin_steps import register_builtins

    register_builtins()


def _load_quality_step() -> None:
    from sm_images.steps.quality import register_quality

    register_quality()  # only when the [quality] extra (cv2) is installed


def _load_anonymize_step() -> None:
    from sm_images.steps.anonymize import register_anonymize

    register_anonymize()  # only when the [anonymize] extra (torch, ultralytics) is installed


_BUILTIN_LOADERS: list[Callable[[], None]] = [
    _load_builtin_steps,
    _load_quality_step,
    _load_anonymize_step,
]
"""Callables that ``register_builtin`` the reserved-id steps, run before plugins."""


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


def _find(pkg: str) -> object | None:
    """The spec of ``<pkg>.images_extensions``, or ``None`` when it has none.

    Only *absence* is skipped: the probed submodule itself missing, or a
    non-package parent (``exc.name`` is the submodule then). A parent that is not
    installed at all is logged and skipped. Anything else - the plugin's own
    ``__init__`` importing a dependency that is not there - is a broken install
    and propagates, instead of silently dropping the plugin's steps.
    """
    name = f"{pkg}.{EXTENSIONS_MODULE}"
    try:
        return importlib.util.find_spec(name)
    except ModuleNotFoundError as exc:
        if exc.name == name:
            return None
        if exc.name == pkg:
            logger.warning("images: entry-point package %r is not importable; skipped", pkg)
            return None
        raise


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
                spec = _find(pkg)
                if spec is None:
                    continue
                module = importlib.import_module(f"{pkg}.{EXTENSIONS_MODULE}")
                module.register(registrar)
            registry.freeze()
        except BaseException:
            registry.reset_registry()
            raise
