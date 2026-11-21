"""What ``app.state.sm_events`` holds."""

from __future__ import annotations

from dataclasses import dataclass

from sm_events.core.settings import EventsSettings


@dataclass
class EventsServices:
    settings: EventsSettings
