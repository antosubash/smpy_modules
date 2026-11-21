"""The module's declarative base.

Alone in its own file so every model file can import it without importing each
other. Every table this module owns is named ``events_<suffix>``.
"""

from __future__ import annotations

from simple_module_db.base import create_module_base

from sm_events.core import constants

Base = create_module_base(constants.BASE_NAME)
