"""The host's public origin, as the reminders read it: the one reader, shared with the public
URLs (:mod:`sm_events.core.host_settings`), so a saved address applies to both at once."""

from __future__ import annotations

from sm_events.core.host_settings import public_base_url

__all__ = ["public_base_url"]
