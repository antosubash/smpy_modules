"""AI metering."""

# The names this path exported as a module before 0.0.14 (#319), listed so
# `from sm_ai.metering import *` still reaches them through __getattr__.
__all__ = ["RequiresAiRequest", "billing_metering_installed", "register_meter"]


def __getattr__(name: str) -> object:
    """The names this path exported as a module before 0.0.14, deprecated until 0.0.17 (#319)."""
    from ..core.moved_paths import moved_attribute

    return moved_attribute(__name__, name)
