"""The process's wall clock, in UTC: the one ``now()`` every module imports.

Modules import it under the name they always called (``now``, ``_now``,
``utcnow``), so a test that pins one module's clock still patches that module's
attribute. Deadlines handed to billing use the database's clock instead
(:mod:`sm_images.clock.db`).
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utcnow"]


def utcnow() -> datetime:
    return datetime.now(UTC)
