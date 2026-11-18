"""What registration checks about a source, an event type and an id (see :mod:`.registry`).

Kept apart from the store so the registry stays small; the exception classes live here and
are re-exported by :mod:`sm_events.calendar.registry`, their public home.
"""

from __future__ import annotations

import inspect
import re
from typing import Any, get_args

from pydantic import BaseModel, SecretBytes, SecretStr

from sm_events.calendar.extension_types import EventType
from sm_events.core import constants

_ID = re.compile(constants.PLUGIN_ID_PATTERN)
_COLOR = re.compile(constants.COLOR_PATTERN)
_ICON = re.compile(r"^[a-z0-9-]{1,40}$")


class DuplicateExtension(ValueError): ...  # noqa: N818 - names fixed by the plan


class InvalidExtensionId(ValueError): ...  # noqa: N818 - names fixed by the plan


class InvalidExtension(TypeError):  # noqa: N818 - names fixed by the plan
    """An object registered as a source or a type does not satisfy its contract."""


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
