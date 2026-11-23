"""What ``app.state.sm_events`` holds."""

from __future__ import annotations

from dataclasses import dataclass

from sm_events.core.settings import EventsSettings


@dataclass
class EventsServices:
    settings: EventsSettings
    public_wired: tuple[str, tuple[str, ...]] | None = None
    """``(prefix, languages)`` once the public routers are mounted, so a second lifespan on
    the same app mounts nothing twice."""
