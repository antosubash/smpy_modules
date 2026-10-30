"""Which settled runs reopen before planning (split from :mod:`.plan`).

A skip the executor decided stands only while its cause does: a placeholder
for a step that could not run (``not_installed``, ``disabled``), and a
dependant blocked by such a step, go back to ``pending`` once it can run.
"""

from __future__ import annotations

from sm_images.models.enums import StepStatus
from sm_images.pipeline.config import PipelineConfig
from sm_images.pipeline.plan import (
    DEPENDENCY_STALE,
    DEPENDENCY_UNAVAILABLE,
    DISABLED,
    NOT_INSTALLED,
    RunView,
    _dep_state,
    effective_deps,
)

__all__ = ["PLACEHOLDER_CODES", "reopenable"]

PLACEHOLDER_CODES = frozenset({NOT_INSTALLED, DISABLED})
"""Skips that only stand in for a step that could not run: they reopen once it can."""


def _cleared(cfg: PipelineConfig, sid: str, state: dict[str, RunView]) -> bool:
    """Whether what blocked ``sid``'s dependency skip no longer holds. An
    enabled prerequisite with no run yet is about to get one: it waits."""
    enabled = set(cfg.enabled())
    states = [
        "unavailable"
        if d not in enabled
        else "wait"
        if d not in state
        else _dep_state(state[d], cfg)
        for d in effective_deps(cfg, sid)
    ]
    if state[sid].error_code == DEPENDENCY_STALE:
        return "stale" not in states and "unavailable" not in states
    return "unavailable" not in states


def reopenable(cfg: PipelineConfig, runs: dict[str, RunView]) -> list[str]:
    """Runs to put back to ``pending`` before planning, or they stay skipped
    for good:

    * placeholder skips (``not_installed``, ``disabled``) of steps that are now
      enabled and installed - a plugin reinstalled, a step switched back on;
    * then, transitively, enabled steps skipped ``dependency_unavailable`` or
      ``dependency_stale`` whose cause has cleared (a prerequisite reopened,
      or enabled again) - they wait for it and run after it.

    A dependant whose prerequisite is still off is left alone, so a dispatch
    with nothing changed reopens nothing (no new cycle, no churn).
    """
    out: set[str] = set()
    state = dict(runs)
    for sid, run in runs.items():
        sc = cfg.get(sid)
        if sc is None or not sc.enabled or sc.state == "not_installed":
            continue
        if run.status is StepStatus.SKIPPED and run.error_code in PLACEHOLDER_CODES:
            out.add(sid)
            state[sid] = RunView(sid)
    waiting = {
        sid
        for sid, run in runs.items()
        if run.status is StepStatus.SKIPPED
        and run.error_code in (DEPENDENCY_UNAVAILABLE, DEPENDENCY_STALE)
        and (sc := cfg.get(sid)) is not None
        and sc.enabled
        and sc.state != "not_installed"
    }
    changed = True
    while changed:
        changed = False
        for sid in sorted(waiting - out):
            if _cleared(cfg, sid, state):
                out.add(sid)
                state[sid] = RunView(sid)
                changed = True
    return sorted(out)
