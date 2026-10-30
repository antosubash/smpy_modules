"""AI steps: ``classify`` and the ``prompt:<id>`` steps (the ``[ai]`` extra).

Both need the ``ai`` module (``sm_ai``) and Pydantic AI. Without them the
steps are absent: ``classify`` is never registered and no prompt resolves, so
a collection that enables either keeps its configuration and the runs settle
as ``not_installed``. Nothing here imports ``sm_ai`` at module load.
"""

from __future__ import annotations

from importlib.util import find_spec

__all__ = ["ai_available"]


def ai_available() -> bool:
    """Whether the ``ai`` module and Pydantic AI are installed."""
    try:
        return find_spec("sm_ai.contracts") is not None and find_spec("pydantic_ai") is not None
    except ModuleNotFoundError:
        return False
