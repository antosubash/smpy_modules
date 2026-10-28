"""The step and preset registry (spec §8.2, plan decision 1).

Process-global and frozen once. It holds implementations only: ``prompt:<id>``
steps are resolved per execution from the database. Registration normally goes
through :func:`sm_images.pipeline.extensions.load_extensions`.
"""

from __future__ import annotations

import re
import threading

from sm_images.pipeline.presets import Preset
from sm_images.pipeline.step import Step

__all__ = [
    "CyclicRequiresError",
    "DuplicateStepError",
    "RegistryFrozenError",
    "ReservedStepIdError",
    "TooManyDisplayMutators",
    "UnresolvedRequiresError",
    "all_presets",
    "all_steps",
    "check_display_mutators",
    "freeze",
    "get_preset",
    "get_step",
    "is_frozen",
    "register_builtin",
    "register_preset",
    "register_step",
    "reset_registry",
    "topo_order",
]

RESERVED_IDS = frozenset({"exif", "renditions", "quality", "anonymize", "classify"})
PROMPT_PREFIX = "prompt:"
PLUGIN_STEP_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
PLUGIN_PRESET_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class RegistryFrozenError(RuntimeError): ...


class DuplicateStepError(ValueError): ...


class ReservedStepIdError(ValueError): ...


class UnresolvedRequiresError(ValueError): ...


class CyclicRequiresError(ValueError): ...


class TooManyDisplayMutators(ValueError):  # noqa: N818 - name fixed by the plan
    ...


_lock = threading.RLock()
_steps: dict[str, Step] = {}
_presets: dict[str, Preset] = {}
_frozen = False


def _is_reserved(step_id: str) -> bool:
    return step_id in RESERVED_IDS or step_id.startswith(PROMPT_PREFIX)


def _add(step: Step, *, builtin: bool) -> None:
    with _lock:
        if _frozen:
            raise RegistryFrozenError(f"registry is frozen; cannot register {step.id!r}")
        if builtin:
            if not _is_reserved(step.id):
                raise ReservedStepIdError(f"built-in id {step.id!r} is not a reserved id")
        elif _is_reserved(step.id):
            raise ReservedStepIdError(f"step id {step.id!r} is reserved for built-in steps")
        elif not PLUGIN_STEP_ID.match(step.id):
            raise ReservedStepIdError(
                f"plugin step id {step.id!r} must be '<plugin>.<name>' (lowercase, [a-z0-9_])"
            )
        if step.id in _steps:
            raise DuplicateStepError(f"step {step.id!r} is already registered")
        _steps[step.id] = step


def register_step(step: Step) -> None:
    _add(step, builtin=False)


def register_builtin(step: Step) -> None:
    """For ``_BUILTIN_LOADERS``: the only path that may use a reserved id."""
    _add(step, builtin=True)


def register_preset(preset: Preset) -> None:
    with _lock:
        if _frozen:
            raise RegistryFrozenError(f"registry is frozen; cannot register preset {preset.id!r}")
        if not PLUGIN_PRESET_ID.match(preset.id):
            raise ReservedStepIdError(f"preset id {preset.id!r} must match [a-z][a-z0-9_]*")
        if preset.id in _presets:
            raise DuplicateStepError(f"preset {preset.id!r} is already registered")
        _presets[preset.id] = preset


def get_step(step_id: str) -> Step | None:
    return _steps.get(step_id)


def get_preset(preset_id: str) -> Preset | None:
    return _presets.get(preset_id)


def all_steps() -> dict[str, Step]:
    return dict(_steps)


def all_presets() -> dict[str, Preset]:
    return dict(_presets)


def is_frozen() -> bool:
    return _frozen


def topo_order(ids: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    """Registered steps in ``requires`` order (Kahn, name-sorted ready set).

    Only edges between ``ids`` count: a requirement outside the set is the
    caller's to satisfy. Raises ``UnresolvedRequiresError`` for an unregistered
    id and ``CyclicRequiresError`` for a cycle.
    """
    wanted = set(ids)
    deps: dict[str, set[str]] = {}
    for sid in wanted:
        step = _steps.get(sid)
        if step is None:
            raise UnresolvedRequiresError(f"step {sid!r} is not registered")
        deps[sid] = {r for r in step.requires if r in wanted}
    order: list[str] = []
    ready = sorted(s for s, d in deps.items() if not d)
    while ready:
        sid = ready.pop(0)
        order.append(sid)
        for other, d in deps.items():
            if sid in d:
                d.discard(sid)
                if not d and other not in order and other not in ready:
                    ready.append(other)
        ready.sort()
    if len(order) != len(deps):
        stuck = sorted(set(deps) - set(order))
        raise CyclicRequiresError(f"cyclic requires among {stuck}")
    return order


def check_display_mutators(step_ids: list[str] | tuple[str, ...] | set[str]) -> None:
    mutators = sorted(
        sid for sid in set(step_ids) if (s := _steps.get(sid)) is not None and s.mutates_display
    )
    if len(mutators) > 1:
        raise TooManyDisplayMutators(f"at most one step may mutate the display copy: {mutators}")


def _validate() -> None:
    for sid, step in _steps.items():
        for req in step.requires:
            if req.startswith(PROMPT_PREFIX):
                continue  # resolved per execution from the database
            if req not in _steps:
                raise UnresolvedRequiresError(f"step {sid!r} requires unregistered {req!r}")
    topo_order(list(_steps))


def freeze() -> None:
    """Validate ``requires`` (resolvable, acyclic) and refuse further changes."""
    global _frozen
    with _lock:
        if _frozen:
            return
        _validate()
        _frozen = True


def reset_registry() -> None:
    """Empty and unfreeze. For tests and a failed load; never at runtime."""
    global _frozen
    with _lock:
        _steps.clear()
        _presets.clear()
        _frozen = False
