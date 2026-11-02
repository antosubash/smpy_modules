"""A collection's ``pipeline_config``, validated against the step registry.

The stored shape is ``{"steps": {id: {"enabled": bool, ...params}}}``. A step
is enabled unless ``enabled`` is ``false``; everything else in its object is
its params, validated by the step's ``params_schema()``.

Two callers, two strictnesses:

* a **save** (``strict=True``, the default) refuses invalid params, a malformed
  shape, more than one enabled display mutator, and a display mutator enabled
  beside an uninstalled (non-``prompt:``) step;
* the **executor** (``strict=False``) reads whatever was saved: a step whose
  params no longer validate is ``invalid`` (its run fails), and the extra
  mutators are ``invalid`` too.

Either way an id with no installed implementation is *kept*, as
``not_installed``: removing a plugin must not silently rewrite a collection's
configuration, and its runs settle as skipped rather than waiting forever.
``prompt:<id>`` steps are never registered: the caller resolves them from the
database per execution (:func:`sm_images.pipeline.ai.prompt_steps.resolve`) and passes
them as ``prompts``. A config-named one it did not pass (a deleted prompt, no
``ai``) is ``not_installed`` too. :meth:`PipelineConfig.with_requested` adds
the resolved prompt runs requested for one image (auto-run, the run route)
that the config does not enable; a requested one that no longer resolves is
not added, and ``advance.advance_locked`` settles its run ``not_installed``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from sm_images.pipeline import registry
from sm_images.pipeline.step import Step

__all__ = [
    "PipelineConfig",
    "PipelineConfigError",
    "StepConfig",
    "protect_originals",
    "validate_pipeline_config",
]

StepState = Literal["ok", "not_installed", "invalid"]


class PipelineConfigError(ValueError):
    """A pipeline configuration that cannot be saved."""


@dataclass(frozen=True)
class StepConfig:
    id: str
    enabled: bool
    state: StepState
    params: BaseModel | None = None
    error: str | None = None

    @property
    def runnable(self) -> bool:
        return self.enabled and self.state == "ok"


@dataclass(frozen=True)
class PipelineConfig:
    steps: dict[str, StepConfig] = field(default_factory=dict)
    prompts: dict[str, Step] = field(default_factory=dict)
    """The collection's ``prompt:<id>`` steps, resolved from the database."""

    def impl(self, step_id: str) -> Step | None:
        """The registered step, else the resolved prompt step, else ``None``."""
        return registry.get_step(step_id) or self.prompts.get(step_id)

    def with_requested(self, step_ids: Iterable[str]) -> PipelineConfig:
        """Enable resolved prompt steps requested for one image, whatever the
        collection's config says. An id that does not resolve is left out:
        ``advance_locked`` settles its run as ``not_installed``."""
        steps = dict(self.steps)
        for sid in step_ids:
            impl = self.prompts.get(sid)
            if impl is not None and not (sid in steps and steps[sid].runnable):
                steps[sid] = StepConfig(sid, True, "ok", params=impl.params_schema()())
        return replace(self, steps=steps)

    def enabled(self) -> list[str]:
        return [s.id for s in self.steps.values() if s.enabled]

    def runnable(self) -> list[str]:
        return [s.id for s in self.steps.values() if s.runnable]

    def get(self, step_id: str) -> StepConfig | None:
        return self.steps.get(step_id)

    def mutators(self) -> list[str]:
        """Enabled, runnable steps that write the display copy."""
        out = []
        for sid in self.runnable():
            impl = registry.get_step(sid)
            if impl is not None and impl.mutates_display:
                out.append(sid)
        return out


def _bad(strict: bool, message: str) -> PipelineConfig:
    if strict:
        raise PipelineConfigError(message)
    return PipelineConfig()


def _one(sid: str, raw: dict[str, Any], strict: bool, prompts: dict[str, Step]) -> StepConfig:
    enabled = raw.get("enabled") is not False
    impl = registry.get_step(sid) or prompts.get(sid)
    if impl is None:
        return StepConfig(sid, enabled, "not_installed")
    params = {k: v for k, v in raw.items() if k != "enabled"}
    try:
        validated = impl.params_schema().model_validate(params)
    except ValidationError as exc:
        if strict:
            raise PipelineConfigError(f"step {sid!r}: invalid params: {exc}") from exc
        return StepConfig(sid, enabled, "invalid", error="invalid_params")
    return StepConfig(sid, enabled, "ok", params=validated)


def validate_pipeline_config(
    cfg: Any, *, strict: bool = True, prompts: Iterable[Step] = ()
) -> PipelineConfig:
    """Parse and validate ``cfg`` (a collection's stored ``pipeline_config``);
    ``prompts`` are the collection's resolved ``prompt:<id>`` steps."""
    from sm_images.pipeline.extensions import load_extensions

    load_extensions()  # the worker's first registry read; a no-op once frozen
    found = {p.id: p for p in prompts}
    if cfg is None or cfg == {}:
        return PipelineConfig(prompts=found)
    if not isinstance(cfg, dict) or not isinstance(cfg.get("steps", {}), dict):
        return _bad(strict, "pipeline_config must be {'steps': {id: {...}}}")
    steps: dict[str, StepConfig] = {}
    for sid, raw in cfg.get("steps", {}).items():
        if not isinstance(sid, str) or not isinstance(raw, dict):
            if strict:
                raise PipelineConfigError(f"step {sid!r}: its value must be an object")
            continue
        steps[sid] = _one(sid, raw, strict, found)
    mutators = PipelineConfig(steps).mutators()
    if len(mutators) > 1:
        if strict:
            raise PipelineConfigError(f"at most one step may mutate the display copy: {mutators}")
        for sid in mutators:
            old = steps[sid]
            steps[sid] = StepConfig(sid, old.enabled, "invalid", error="too_many_display_mutators")
    out = PipelineConfig(steps, found)
    if strict:
        _check_unknown_beside_mutator(out)
        _check_graph(out)
    return out


def _check_unknown_beside_mutator(cfg: PipelineConfig) -> None:
    """A save must not enable a display mutator beside an uninstalled step:
    the unknown step might mutate the display too, so serving would never
    trust the mutator's copy (``redaction.trusts_display``)."""
    mutators = cfg.mutators()
    unknown = [
        s.id
        for s in cfg.steps.values()
        if s.enabled and s.state == "not_installed" and not s.id.startswith(registry.PROMPT_PREFIX)
    ]
    if mutators and unknown:
        raise PipelineConfigError(
            f"a display mutator {mutators} cannot be enabled beside steps that are "
            f"not installed: {sorted(unknown)}; disable or remove them, or install them"
        )


def _check_graph(cfg: PipelineConfig) -> None:
    """A save must not enable a step whose prerequisites are off, nor a cycle
    the implicit rendition edge closes (the executor would only settle them)."""
    from sm_images.pipeline.plan import effective_deps, graph_problems

    unmet, cyclic = graph_problems(cfg)
    if unmet:
        enabled = set(cfg.enabled())
        missing = {sid: sorted(set(effective_deps(cfg, sid)) - enabled) for sid in sorted(unmet)}
        raise PipelineConfigError(f"enabled steps require steps that are not enabled: {missing}")
    if cyclic:
        raise PipelineConfigError(f"steps depend on each other in a cycle: {sorted(cyclic)}")


def _registered_mutator(sid: str) -> bool:
    impl = registry.get_step(sid)
    return impl is not None and bool(impl.mutates_display)


def protect_originals(current: bool, cfg: PipelineConfig) -> bool:
    """``Collection.protect_originals`` after an owner saves *cfg*.

    Set when an enabled step is a registered display mutator. Cleared only by
    a save with no mutator enabled *and* every step installed: a config naming
    a step that is not installed (a plugin removed) might be naming the
    mutator, so it keeps whatever protection there was. ``prompt:*`` steps
    never write a display copy and do not count as missing.
    """
    if any(_registered_mutator(sid) for sid in cfg.enabled()):
        return True
    missing = [
        s.id
        for s in cfg.steps.values()
        if s.state == "not_installed" and not s.id.startswith(registry.PROMPT_PREFIX)
    ]
    return current if missing else False
