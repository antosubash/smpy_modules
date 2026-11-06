"""The module's declarative base.

Alone in its own file so every model file can import it without importing each
other. Every table this module owns is named ``newsletter_<suffix>``.
"""

from __future__ import annotations

from simple_module_db.base import create_module_base

from sm_newsletter.core import constants

Base = create_module_base(constants.BASE_NAME)
