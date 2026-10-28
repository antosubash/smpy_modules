"""Which of an image's steps run next: a pure function over its step runs.

The status rules (spec §3, which fix the portal's SKIPPED re-run bug):

* ``skipped`` (the step's own "does not apply") and ``completed`` are final for
  that ``step_version``; automatic dispatch never re-runs them, and a version
  bump only makes them **stale** (shown, re-run by "re-run stale" or ``force``);
* a ``failed`` step never blocks an independent one. Its dependants are
  *settled* as skipped with ``dependency_failed`` - a **blocked** skip, which,
  unlike an ordinary one, does not satisfy anything downstream and is reset by
  a retry together with the failure that caused it.

A step is **ready** when every effective dependency is completed or ordinarily
skipped *at the current version*. Effective dependencies are the declared
``requires`` plus, for ``renditions``, the enabled display mutator: thumbnails
are cut from the display copy. A declared requirement the collection does not
enable is **unmet**: the dependant settles as ``dependency_unavailable`` (a
save refuses such a config; one saved before a plugin changed still settles).

The implicit rendition edge is added after the registry validated its graph,
so a mutator that requires ``renditions`` would close a cycle the registry
never saw. Such steps settle as failed ``invalid_pipeline`` instead of
waiting forever (and a save refuses them: :func:`graph_problems`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sm_images.models.enums import StepStatus
from sm_images.pipeline import registry
from sm_images.pipeline.config import PipelineConfig

__all__ = [
    "BLOCKED_CODES",
    "FINAL",
    "Plan",
    "RunView",
    "Settle",
    "effective_deps",
    "graph_problems",
    "is_blocked",
    "is_stale",
    "plan",
    "reopenable",
]

RENDITIONS = "renditions"
FINAL = frozenset({StepStatus.COMPLETED, StepStatus.SKIPPED, StepStatus.FAILED})

DEPENDENCY_FAILED = "dependency_failed"
DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
DEPENDENCY_STALE = "dependency_stale"
NOT_INSTALLED = "not_installed"
DISABLED = "disabled"
INVALID_PIPELINE = "invalid_pipeline"
BLOCKED_CODES = frozenset(
    {DEPENDENCY_FAILED, DEPENDENCY_UNAVAILABLE, DEPENDENCY_STALE, NOT_INSTALLED, DISABLED}
)
"""``error_code`` of a skip the executor decided, not the step: never a prerequisite."""
PLACEHOLDER_CODES = frozenset({NOT_INSTALLED, DISABLED})
"""Skips that only stand in for a step that could not run: they reopen once it can."""


@dataclass(frozen=True)
class RunView:
    step: str
    status: StepStatus = StepStatus.PENDING
    step_version: int | None = None
    error_code: str | None = None
    lease_live: bool = False
    """``RUNNING`` with an unexpired lease (someone is working on it)."""


@dataclass(frozen=True)
class Settle:
    step: str
    status: StepStatus
    code: str


@dataclass
class Plan:
    missing: list[str] = field(default_factory=list)
    settle: list[Settle] = field(default_factory=list)
    ready: list[str] = field(default_factory=list)
    final: bool = False


def is_blocked(run: RunView) -> bool:
    return run.status is StepStatus.SKIPPED and run.error_code in BLOCKED_CODES


def is_stale(run: RunView) -> bool:
    """A final result produced by an older version of an installed step."""
    if run.status not in (StepStatus.COMPLETED, StepStatus.SKIPPED) or is_blocked(run):
        return False
    impl = registry.get_step(run.step)
    return impl is not None and run.step_version != impl.version


def effective_deps(cfg: PipelineConfig, step_id: str) -> list[str]:
    impl = registry.get_step(step_id)
    deps = [r for r in (impl.requires if impl else ()) if r != step_id]
    if step_id == RENDITIONS:
        deps += [m for m in cfg.mutators() if m not in deps and m != step_id]
    return deps


def _cyclic(graph: dict[str, set[str]]) -> set[str]:
    """Steps on a cycle of ``graph`` (step -> its dependencies)."""
    out: set[str] = set()
    for start in graph:
        seen: set[str] = set()
        todo = list(graph[start])
        while todo:
            node = todo.pop()
            if node == start:
                out.add(start)
                break
            if node not in seen:
                seen.add(node)
                todo.extend(graph.get(node, ()))
    return out


def graph_problems(cfg: PipelineConfig) -> tuple[set[str], set[str]]:
    """``(unmet, cyclic)``: enabled steps requiring a step that is not enabled,
    and enabled steps on a dependency cycle (implicit edges included)."""
    enabled = set(cfg.enabled())
    deps = {sid: set(effective_deps(cfg, sid)) for sid in enabled}
    unmet = {sid for sid, d in deps.items() if d - enabled}
    return unmet, _cyclic({sid: d & enabled for sid, d in deps.items()})


def _order(cfg: PipelineConfig, cyclic: set[str]) -> list[str]:
    """Enabled steps, dependencies first (Kahn; name order among the ready).
    Cyclic steps come first: they settle without waiting on anything."""
    enabled = set(cfg.enabled())
    deps = {
        sid: {d for d in effective_deps(cfg, sid) if d in enabled and d not in cyclic}
        for sid in enabled - cyclic
    }
    order = sorted(cyclic)
    while deps:
        ready = sorted(s for s, d in deps.items() if not d) or sorted(deps)
        for sid in ready:
            order.append(sid)
            del deps[sid]
        for d in deps.values():
            d.difference_update(ready)
    return order


def _dep_state(run: RunView | None) -> str:
    if run is None:  # required, but not enabled in this collection
        return "unavailable"
    if run.status in (StepStatus.PENDING, StepStatus.RUNNING):
        return "wait"
    if run.status is StepStatus.FAILED or run.error_code == DEPENDENCY_FAILED:
        return "failed"
    if is_blocked(run):
        return "stale" if run.error_code == DEPENDENCY_STALE else "unavailable"
    return "stale" if is_stale(run) else "ok"


def _blocked_code(states: list[str]) -> str | None:
    if "failed" in states:
        return DEPENDENCY_FAILED
    if "unavailable" in states:
        return DEPENDENCY_UNAVAILABLE
    if "stale" in states:
        return DEPENDENCY_STALE
    return None


def plan(cfg: PipelineConfig, runs: dict[str, RunView]) -> Plan:
    """What to insert, settle and claim for one image, and whether it is done."""
    out = Plan()
    enabled = cfg.enabled()
    state = dict(runs)
    for sid in enabled:
        if sid not in state:
            out.missing.append(sid)
            state[sid] = RunView(sid)
    for sid, run in runs.items():
        abandoned = run.status is StepStatus.RUNNING and not run.lease_live
        if sid not in enabled and (run.status is StepStatus.PENDING or abandoned):
            out.settle.append(Settle(sid, StepStatus.SKIPPED, DISABLED))
            state.pop(sid)

    def settle(sid: str, status: StepStatus, code: str) -> None:
        out.settle.append(Settle(sid, status, code))
        state[sid] = RunView(sid, status, state[sid].step_version, code)

    _, cyclic = graph_problems(cfg)
    for sid in _order(cfg, cyclic):
        run = state[sid]
        claimable = run.status is StepStatus.PENDING or (
            run.status is StepStatus.RUNNING and not run.lease_live
        )
        if not claimable:
            continue
        sc = cfg.steps[sid]
        # A claimable run is pending or abandoned (expired lease); settling
        # either is safe under the image lock (``claim.settle`` re-checks).
        if sc.state == "not_installed":
            settle(sid, StepStatus.SKIPPED, NOT_INSTALLED)
            continue
        if sc.state == "invalid":
            settle(sid, StepStatus.FAILED, sc.error or "invalid_config")
            continue
        if sid in cyclic:
            settle(sid, StepStatus.FAILED, INVALID_PIPELINE)
            continue
        # A prerequisite the collection does not enable is unavailable whatever
        # its old run says: a completed result from before it was disabled
        # does not satisfy anything under this configuration.
        states = [
            _dep_state(state.get(d)) if d in enabled else "unavailable"
            for d in effective_deps(cfg, sid)
        ]
        code = _blocked_code(states)
        if code is not None:
            settle(sid, StepStatus.SKIPPED, code)
        elif all(s == "ok" for s in states):
            out.ready.append(sid)
    out.final = not out.ready and all(state[s].status in FINAL for s in enabled)
    return out


def reopenable(cfg: PipelineConfig, runs: dict[str, RunView]) -> list[str]:
    """Placeholder skips (``not_installed``, ``disabled``) of steps that are now
    enabled and installed: back to ``pending`` before planning, or a plugin
    reinstalled (or a step switched back on) would stay skipped for good."""
    out = []
    for sid, run in runs.items():
        sc = cfg.get(sid)
        if sc is None or not sc.enabled or sc.state == "not_installed":
            continue
        if run.status is StepStatus.SKIPPED and run.error_code in PLACEHOLDER_CODES:
            out.append(sid)
    return sorted(out)
