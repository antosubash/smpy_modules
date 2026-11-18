"""The source and event-type registry (process-global, frozen once).

Registration normally goes through :func:`sm_events.calendar.extensions.load_extensions`,
which registers the built-ins, then every installed package's ``events_extensions``,
then freezes. The registry is the trust boundary for plugins: an id must be
``<entry-point name>:<name>`` and match the namespace its :class:`Registrar` was built
for, a malformed object is refused at registration (so it fails the boot, not a read),
and nothing registers after the freeze. Every getter calls :func:`ensure_loaded`, so a
Celery worker, which runs no module hook, loads exactly what the web process loads on
its first read.
"""

from __future__ import annotations

import inspect
import re
import threading
from typing import Any, get_args

from pydantic import BaseModel, SecretBytes, SecretStr

from sm_events.calendar.extension_types import EventType, Source
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

_ID = re.compile(constants.PLUGIN_ID_PATTERN)
_COLOR = re.compile(constants.COLOR_PATTERN)
_ICON = re.compile(r"^[a-z0-9-]{1,40}$")


class RegistryFrozenError(RuntimeError): ...


class DuplicateExtension(ValueError): ...  # noqa: N818 - names fixed by the plan


class InvalidExtensionId(ValueError): ...  # noqa: N818 - names fixed by the plan


class InvalidExtension(TypeError):  # noqa: N818 - names fixed by the plan
    """An object registered as a source or a type does not satisfy its contract."""


lock = threading.RLock()
_sources: dict[str, Source] = {}
_types: dict[str, EventType] = {}
_builtin_source: Any = None
_frozen = False
_loading = False


def _check_id(kind: str, ident: Any, namespace: str | None) -> str:
    """A plugin id is ``<namespace>:<name>``; the built-ins register with no namespace."""
    where = f" (plugin {namespace!r})" if namespace else ""
    if not isinstance(ident, str) or not ident:
        raise InvalidExtension(f"{kind} id must be a non-empty str, got {ident!r}{where}")
    if namespace is None:
        return ident
    if not _ID.match(ident):
        raise InvalidExtensionId(
            f"{kind} id {ident!r}{where} must look like '<plugin>:<name>' "
            f"(lowercase, [a-z0-9_], at most 48 characters after the colon)"
        )
    if ident.split(":", 1)[0] != namespace:
        raise InvalidExtensionId(
            f"{kind} id {ident!r} must start with the plugin's entry-point name '{namespace}:'"
        )
    return ident


KEEP_SECRETS_ELSEWHERE = (
    "source settings are stored in the clear, so a secret-typed field is refused; keep the secret "
    "in your own module's settings (sealed there) and name it from the settings here"
)


def _is_secret(annotation: Any, metadata: tuple[Any, ...], seen: set[Any]) -> bool:
    """Whether a field holds a secret: pydantic's ``SecretStr``/``SecretBytes`` (anywhere in its
    type, lists and unions included, or in a nested model), or records' ``SealedSecret`` (a
    serializer named ``seal_secret``)."""
    if any(getattr(getattr(m, "func", None), "__name__", "") == "seal_secret" for m in metadata):
        return True
    if isinstance(annotation, type):
        if issubclass(annotation, SecretStr | SecretBytes):
            return True
        if issubclass(annotation, BaseModel) and annotation not in seen:
            seen.add(annotation)
            return any(
                _is_secret(f.annotation, tuple(f.metadata), seen)
                for f in annotation.model_fields.values()
            )
    return any(
        _is_secret(arg, (*metadata, *getattr(arg, "__metadata__", ())), seen)
        for arg in get_args(annotation)
    )


def _check_model(label: str, model: Any, *, forbid_extra: bool, secrets: bool = False) -> None:
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise InvalidExtension(f"{label}: must be a pydantic BaseModel subclass, got {model!r}")
    if forbid_extra and model.model_config.get("extra") != "forbid":
        raise InvalidExtension(f"{label}: the model must set extra='forbid'")
    if secrets:
        for name, info in model.model_fields.items():
            if _is_secret(info.annotation, tuple(info.metadata), {model}):
                raise InvalidExtension(
                    f"{label}: field {name!r} is a secret. {KEEP_SECRETS_ELSEWHERE}"
                )
    try:
        model.model_json_schema()
    except Exception as exc:
        raise InvalidExtension(
            f"{label}: its JSON schema cannot be built ({type(exc).__name__})"
        ) from exc


def _check_source(source: Any, label: str, *, builtin: bool = False) -> None:
    for name in ("id", "label_key"):
        value = getattr(source, name, None)
        if not isinstance(value, str) or not value:
            raise InvalidExtension(f"{label}: {name} must be a non-empty str")
    if not isinstance(getattr(source, "public", None), bool):
        raise InvalidExtension(f"{label}: public must be a bool")
    color = getattr(source, "color", None)
    if color is not None and not (isinstance(color, str) and _COLOR.match(color)):
        raise InvalidExtension(f"{label}: color must be '#rrggbb' or None")
    icon = getattr(source, "icon", None)
    if icon is not None and not (isinstance(icon, str) and _ICON.match(icon)):
        raise InvalidExtension(f"{label}: icon must match [a-z0-9-]{{1,40}} or None")
    model = getattr(source, "settings_model", None)
    if model is not None:
        _check_model(f"{label}: settings_model", model, forbid_extra=False, secrets=True)
    read = getattr(source, "occurrences", None)
    if builtin:  # the internal protocol: an async generator over the read's own context
        if not inspect.isasyncgenfunction(read):
            raise InvalidExtension(f"{label}: occurrences must be an async generator")
    elif not inspect.iscoroutinefunction(read):
        raise InvalidExtension(f"{label}: occurrences must be an 'async def' method")
    check = getattr(source, "check_settings", None)
    if check is not None and not inspect.iscoroutinefunction(check):
        raise InvalidExtension(f"{label}: check_settings must be an 'async def' method")


def _check_type(etype: Any, label: str) -> None:
    if not isinstance(etype, EventType):
        raise InvalidExtension(f"{label}: must be an EventType, got {type(etype).__name__}")
    for name in ("id", "label_key"):
        value = getattr(etype, name)
        if not isinstance(value, str) or not value:
            raise InvalidExtension(f"{label}: {name} must be a non-empty str")
    _check_model(f"{label}: extra_model", etype.extra_model, forbid_extra=True)
    public = etype.public_fields
    if not isinstance(public, frozenset) or not all(isinstance(n, str) for n in public):
        raise InvalidExtension(f"{label}: public_fields must be a frozenset of str")
    unknown = sorted(public - set(etype.extra_model.model_fields))
    if unknown:
        raise InvalidExtension(f"{label}: public_fields {unknown} are not fields of its model")
    if etype.icon is not None and not (isinstance(etype.icon, str) and _ICON.match(etype.icon)):
        raise InvalidExtension(f"{label}: icon must match [a-z0-9-]{{1,40}} or None")


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
        from sm_events.calendar import extensions

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
