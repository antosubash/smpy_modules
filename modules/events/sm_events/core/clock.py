"""The process's wall clock, in UTC: the one ``now()`` the module imports."""

from __future__ import annotations

from simple_module_core.datetimes import utcnow

__all__ = ["utcnow"]
