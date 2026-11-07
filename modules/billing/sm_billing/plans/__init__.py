"""Billing plans."""

# The names this path exported as a module before 0.0.14 (#319), listed so
# `from sm_billing.plans import *` still reaches them through __getattr__.
__all__ = ["PlanError", "PlanService", "logger", "seed_default_plan"]


def __getattr__(name: str) -> object:
    """The names this path exported as a module before 0.0.14, deprecated until 0.0.17 (#319)."""
    from ..core.moved_paths import moved_attribute

    return moved_attribute(__name__, name)
