"""Per-seat quantity sync on membership changes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI
    from simple_module_core.events import EventBus


def subscribe(bus: EventBus, app: FastAPI) -> None:
    """Subscribe the membership handlers."""
