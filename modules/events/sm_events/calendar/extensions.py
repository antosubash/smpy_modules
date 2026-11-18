"""Plugin discovery, as images does it (``sm_images.pipeline.extensions``).

A plugin is an ordinary framework module (it has the ``simple_module`` entry point)
whose package ships ``events_extensions.py`` with ``def register(registry) -> None``.
Workers never build the app, so registration cannot hang off ``on_startup``: the web
process (events' ``on_startup``) and a worker (on its first registry read) both call
:func:`load_extensions`, one code path, so both see the same registry. A plugin that
raises while loading fails the load (and so the boot) with the plugin named; the
registry is emptied so the next attempt starts clean.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
from collections.abc import Callable

from sm_events.calendar import registry
from sm_events.calendar.extension_types import EventType, Source
from sm_events.core import constants

__all__ = ["Registrar", "load_extensions"]

logger = logging.getLogger(__name__)


def _load_builtins() -> None:
    from sm_events.calendar.sources import register_builtins

    register_builtins()


_BUILTIN_LOADERS: list[Callable[[], None]] = [_load_builtins]
"""Callables that register the reserved-id source and type, run before plugins."""


class Registrar:
    """What a plugin's ``register`` receives: registration only (no freeze, no reset,
    no reserved ids), under the entry-point name it was built for."""

    def __init__(self, namespace: str) -> None:
        self._namespace = namespace

    def add_source(self, source: Source) -> None:
        registry.add_source(source, namespace=self._namespace)

    def add_type(self, etype: EventType) -> None:
        registry.add_type(etype, namespace=self._namespace)


def _plugins() -> list[tuple[str, str]]:
    """``(package, entry-point name)`` per installed module package, by package name."""
    found: dict[str, str] = {}
    for ep in importlib.metadata.entry_points(group=constants.ENTRY_POINT_GROUP):
        pkg = ep.value.split(":")[0].split(".")[0]
        name = getattr(ep, "name", pkg)
        found[pkg] = min(name, found.get(pkg, name))
    return sorted(found.items())


def _find(pkg: str) -> object | None:
    """The spec of ``<pkg>.events_extensions``, or ``None`` when it has none.

    Only *absence* is skipped: the probed submodule itself missing, or a
    non-package parent (``exc.name`` is the submodule then). A parent that is not
    installed at all is logged and skipped. Anything else - the plugin's own
    ``__init__`` importing a dependency that is not there - is a broken install
    and propagates, instead of silently dropping the plugin.
    """
    name = f"{pkg}.{constants.EXTENSIONS_MODULE}"
    try:
        return importlib.util.find_spec(name)
    except ModuleNotFoundError as exc:
        if exc.name == name:
            return None
        if exc.name == pkg:
            logger.warning("events: entry-point package %r is not importable; skipped", pkg)
            return None
        raise


def _load_plugin(pkg: str, namespace: str) -> None:
    if _find(pkg) is None:
        return
    try:
        module = importlib.import_module(f"{pkg}.{constants.EXTENSIONS_MODULE}")
        module.register(Registrar(namespace))
    except Exception as exc:
        exc.add_note(f"while loading the events plugin {pkg!r} (entry point {namespace!r})")
        raise


def load_extensions() -> None:
    """Register the built-ins, then every installed plugin's, then freeze. A second
    call is a no-op. A failure empties the registry so a retry starts clean."""
    with registry.lock:
        if registry.is_frozen():
            return
        registry._set_loading(True)
        try:
            for loader in _BUILTIN_LOADERS:
                loader()
            for pkg, namespace in _plugins():
                _load_plugin(pkg, namespace)
            registry.freeze()
        except BaseException:
            registry.reset_registry()
            raise
        finally:
            registry._set_loading(False)
