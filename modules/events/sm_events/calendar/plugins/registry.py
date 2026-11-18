"""The source and event-type registry (process-global, frozen once).

Registration normally goes through :func:`sm_events.calendar.plugins.extensions.load_extensions`,
which registers the built-ins, then every installed package's ``events_extensions``,
then freezes. The registry is the trust boundary for plugins: an id must be
``<entry-point name>:<name>`` and match the namespace its :class:`Registrar` was built
for, a malformed object is refused at registration (so it fails the boot, not a read),
and nothing registers after the freeze. Every getter calls :func:`ensure_loaded`, so a
Celery worker, which runs no module hook, loads exactly what the web process loads on
its first read.
"""

from __future__ import annotations

import threading
from typing import Any

from sm_events.calendar.plugins.extension_types import EventType, Source
from sm_events.calendar.plugins.registry_checks import (
    DuplicateExtension,
    InvalidExtension,
    InvalidExtensionId,
    _check_id,
    _check_source,
    _check_type,
)
from sm_events.core import constants

__all__ = [
    "DuplicateExtension",
    "InvalidExtension",
    "InvalidExtensionId",
    "RegistryFrozenError",
    "add_source",
    "add_type",
    "all_types",
    "builtin_source",
    "ensure_loaded",
    "freeze",
    "get_source",
    "get_type",
    "is_frozen",
    "plugin_sources",
    "register_builtin_source",
    "register_builtin_type",
    "reset_registry",
]


class RegistryFrozenError(RuntimeError): ...


lock = threading.RLock()
_sources: dict[str, Source] = {}
_types: dict[str, EventType] = {}
_builtin_source: Any = None
_frozen = False
_loading = False


def _label(kind: str, obj: Any, namespace: str | None) -> str:
    ident = getattr(obj, "id", None)
    return f"{kind} {ident!r}" + (f" of plugin {namespace!r}" if namespace else "")


def add_source(source: Source, *, namespace: str) -> None:
    """A plugin's source: its id is ``<namespace>:<name>``."""
    label = _label("source", source, namespace)
    _check_id("source", getattr(source, "id", None), namespace)
    _check_source(source, label)
    with lock:
        if _frozen:
            raise RegistryFrozenError(f"registry is frozen; cannot register {label}")
        if source.id in _sources:
            raise DuplicateExtension(f"{label} is already registered")
        _sources[source.id] = source


def add_type(etype: EventType, *, namespace: str) -> None:
    """A plugin's event type: its id is ``<namespace>:<name>``."""
    label = _label("type", etype, namespace)
    _check_type(etype, label)
    _check_id("type", etype.id, namespace)
    with lock:
        if _frozen:
            raise RegistryFrozenError(f"registry is frozen; cannot register {label}")
        if etype.id in _types:
            raise DuplicateExtension(f"{label} is already registered")
        _types[etype.id] = etype


def register_builtin_source(source: Any) -> None:
    """For the built-in loaders only: the one path that may use the reserved id."""
    global _builtin_source
    if getattr(source, "id", None) != constants.SOURCE_EVENTS:
        raise InvalidExtensionId(f"the built-in source id must be {constants.SOURCE_EVENTS!r}")
    _check_source(source, "built-in source", builtin=True)
    with lock:
        if _frozen:
            raise RegistryFrozenError("registry is frozen; cannot register the built-in source")
        if _builtin_source is not None:
            raise DuplicateExtension("the built-in source is already registered")
        _builtin_source = source


def register_builtin_type(etype: EventType) -> None:
    if getattr(etype, "id", None) != constants.BUILTIN_TYPE:
        raise InvalidExtensionId(f"the built-in type id must be {constants.BUILTIN_TYPE!r}")
    _check_type(etype, "built-in type")
    with lock:
        if _frozen:
            raise RegistryFrozenError("registry is frozen; cannot register the built-in type")
        if etype.id in _types:
            raise DuplicateExtension("the built-in type is already registered")
        _types[etype.id] = etype


def ensure_loaded() -> None:
    """Load (once) what the web process loads, then return. Re-entrant: a plugin that
    reads the registry while it registers sees what is registered so far."""
    with lock:
        if _frozen or _loading:
            return
        from sm_events.calendar.plugins import extensions

        extensions.load_extensions()


def get_source(source_id: str) -> Source | None:
    ensure_loaded()
    return _sources.get(source_id)


def plugin_sources() -> dict[str, Source]:
    """Every plugin source, by id; the built-in ``events`` is not among them."""
    ensure_loaded()
    return dict(_sources)


def builtin_source() -> Any:
    ensure_loaded()
    return _builtin_source


def get_type(type_id: str) -> EventType | None:
    ensure_loaded()
    return _types.get(type_id)


def all_types() -> dict[str, EventType]:
    ensure_loaded()
    return dict(_types)


def is_frozen() -> bool:
    return _frozen


def freeze() -> None:
    global _frozen
    with lock:
        _frozen = True


def reset_registry() -> None:
    """Tests, and a failed load: forget everything and unfreeze."""
    global _builtin_source, _frozen, _loading
    with lock:
        _sources.clear()
        _types.clear()
        _builtin_source = None
        _frozen = False
        _loading = False


def _set_loading(value: bool) -> None:
    global _loading
    _loading = value
