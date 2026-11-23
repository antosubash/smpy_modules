"""The process's wall clock, in UTC: the one ``now()`` the module imports.

:func:`utcnow` is the clock itself. :func:`now` is what the public surface and the cards
contract read, as one name a test replaces (``monkeypatch.setattr(clock, "now", ...)``) to fix
"now" for every public answer at once.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_core.datetimes import utcnow

__all__ = ["now", "utcnow"]


def now() -> datetime:
    return utcnow()
